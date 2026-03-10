import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import traci

try:
    import pymongo
except Exception:
    pymongo = None


class SystemAnalyticsStore:
    """Lane-window analytics writer and query service for execution mode."""

    ACTION_EDGE_MAP = {
        "J1": {
            0: ["-E2"],
            1: ["-E3"],
            2: ["E00"],
        },
        "J4": {
            0: ["-E0", "E0"],
            1: ["J4_c0", "J4_c1"],
        },
        "J8": {
            0: ["-E4"],
            1: ["E3"],
            2: ["-E5"],
            3: ["-E8"],
        },
    }

    LANE_META_BY_EDGE = {
        "J1": {
            "-E2": {"lane_name": "Weliwita Road", "direction": "north"},
            "E00": {"lane_name": "Kaduwela Road", "direction": "east"},
            "-E3": {"lane_name": "New Kandy Road", "direction": "west"},
        },
        "J4": {
            "-E0": {"lane_name": "Malabe Road", "direction": "west"},
            "E0": {"lane_name": "New Kandy Road", "direction": "east"},
            "J4_c0": {"lane_name": "Pedestrian Crossing North", "direction": "crossing"},
            "J4_c1": {"lane_name": "Pedestrian Crossing South", "direction": "crossing"},
        },
        "J8": {
            "-E4": {"lane_name": "Kaduwela Road", "direction": "north"},
            "-E5": {"lane_name": "New Kandy Road", "direction": "east"},
            "-E8": {"lane_name": "Awissawella Road", "direction": "south"},
            "E3": {"lane_name": "Malabe Road", "direction": "west"},
        },
    }

    def __init__(self, env_config: Dict[str, Any], sumo_cfg: str):
        self.enabled = bool(env_config.get("analytics_enabled", True)) and (pymongo is not None)
        self.window_sec = max(30, int(env_config.get("analytics_window_sec", 300)))
        self.step_sec = float(env_config.get("analytics_step_sec", 1.0))
        self.scenario_id = str(env_config.get("analytics_scenario_id", "3junctions"))
        self.sumo_cfg = str(sumo_cfg)
        self.run_id = f"exec_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}"

        self.client = None
        self.collection = None
        self.window_start_epoch = time.time()
        self.acc: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Per-window transition memory for unique moving->stopped stop events.
        self._emergency_prev_stopped: Dict[str, bool] = {}

        if not self.enabled:
            return

        try:
            mongo_uri = str(
                env_config.get(
                    "mongo_uri",
                    "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
                )
            )
            mongo_db = str(env_config.get("analytics_mongo_db", "EmergencyDetection"))
            collection_name = str(env_config.get("analytics_collection", "System_Analytics"))

            self.client = pymongo.MongoClient(mongo_uri)
            self.client.admin.command("ping")
            db = self.client[mongo_db]
            self.collection = db[collection_name]
            self._ensure_indexes()
        except Exception:
            self.enabled = False
            self.client = None
            self.collection = None

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass

    def _ensure_indexes(self) -> None:
        if self.collection is None:
            return
        try:
            self.collection.create_index([("doc_type", 1), ("window.start_ts", -1)])
            self.collection.create_index([("mode.mode_variant", 1), ("window.start_ts", -1)])
            self.collection.create_index([("location.junction_id", 1), ("window.start_ts", -1)])
            self.collection.create_index([("location.lane_id", 1), ("window.start_ts", -1)])
            self.collection.create_index([("run.run_id", 1), ("window.start_ts", -1)])
        except Exception:
            pass

    @staticmethod
    def _edge_from_lane(lane_id: str) -> str:
        if "_" not in lane_id:
            return lane_id
        return lane_id.rsplit("_", 1)[0]

    def _mode_payload(self, lane_mode: str, fixed_state: Dict[str, Any]) -> Dict[str, Any]:
        vehicle_sec = int(fixed_state.get("vehicle_green_steps", fixed_state.get("green_steps", 40)))
        ped_sec = int(fixed_state.get("pedestrian_green_steps", 15))

        if lane_mode == "fixed":
            mode_variant = f"fixed_{vehicle_sec}"
        elif lane_mode == "manual":
            mode_variant = "police"
        else:
            mode_variant = "marl"

        return {
            "global_mode": lane_mode,
            "mode_variant": mode_variant,
            "fixed_vehicle_green_sec": vehicle_sec,
            "fixed_pedestrian_green_sec": ped_sec,
        }

    def _lane_meta(self, junction_id: str, edge_id: str, lane_id: str, lane_type: str) -> Dict[str, str]:
        by_edge = self.LANE_META_BY_EDGE.get(junction_id, {}).get(edge_id, {})
        lane_name = by_edge.get("lane_name", edge_id if edge_id else lane_id)
        direction = by_edge.get("direction", "unknown")
        return {
            "junction_id": junction_id,
            "lane_id": lane_id,
            "lane_name": lane_name,
            "lane_type": lane_type,
            "direction": direction,
        }

    def _key(self, junction_id: str, lane_id: str) -> Tuple[str, str]:
        return junction_id, lane_id

    def _get_bucket(
        self,
        junction_id: str,
        lane_id: str,
        lane_type: str,
        lane_mode: str,
        fixed_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        key = self._key(junction_id, lane_id)
        if key in self.acc:
            return self.acc[key]

        edge_id = "pedestrian" if lane_type == "pedestrian" else self._edge_from_lane(lane_id)
        bucket = {
            "run": {
                "run_id": self.run_id,
                "scenario_id": self.scenario_id,
                "sumo_cfg": self.sumo_cfg,
            },
            "mode": self._mode_payload(lane_mode, fixed_state),
            "location": self._lane_meta(junction_id, edge_id, lane_id, lane_type),
            "counts": {
                "vehicles_seen": 0.0,
                "emergency_seen": 0.0,
                "pedestrians_seen": 0.0,
                "throughput_total": 0.0,
                "throughput_emergency": 0.0,
            },
            "wait_time_sec": {
                "vehicle_sum": 0.0,
                "vehicle_count": 0.0,
                "emergency_sum": 0.0,
                "emergency_count": 0.0,
                "pedestrian_sum": 0.0,
                "pedestrian_count": 0.0,
            },
            "speed": {
                "vehicle_speed_sum_mps": 0.0,
                "vehicle_speed_count": 0.0,
            },
            "quality": {
                "emergency_stops": 0.0,
                "green_no_stopped_events": 0.0,
                "green_no_stopped_vehicle_sec": 0.0,
                "green_no_stopped_pedestrian_sec": 0.0,
                "green_no_stopped_sec": 0.0,
                "green_total_sec": 0.0,
            },
        }
        self.acc[key] = bucket
        return bucket

    def _green_edges_for_action(self, junction_id: str, action: int, is_yellow: bool) -> List[str]:
        if is_yellow:
            return []
        return list(self.ACTION_EDGE_MAP.get(junction_id, {}).get(int(action), []))

    def observe_step(
        self,
        step_meta: Dict[str, Dict[str, float]],
        actions: Dict[str, int],
        junction_modes: Dict[str, str],
        fixed_state: Dict[str, Dict[str, int]],
        junction_live_metrics: Dict[str, Dict[str, Any]],
    ) -> None:
        if not self.enabled:
            return

        now_epoch = time.time()

        for junction_id, live in (junction_live_metrics or {}).items():
            lane_mode = str(junction_modes.get(junction_id, "marl"))
            fixed = dict(fixed_state.get(junction_id, {}))
            meta = dict((step_meta or {}).get(junction_id, {}))
            action = int((actions or {}).get(junction_id, 0))
            green_edges = set(self._green_edges_for_action(junction_id, action, bool(meta.get("is_yellow", 0.0) > 0.5)))

            lane_metrics = dict(live.get("lane_metrics", {}))
            for lane_id, metrics in lane_metrics.items():
                bucket = self._get_bucket(junction_id, lane_id, "vehicle", lane_mode, fixed)
                edge_id = self._edge_from_lane(lane_id)

                total = float(metrics.get("total_vehicles", 0.0))
                stopped = float(metrics.get("stopped_vehicles", 0.0))
                emergency = float(metrics.get("emergency_total", 0.0))
                avg_wait = float(metrics.get("avg_wait_stopped", 0.0))
                avg_speed = float(metrics.get("avg_speed_hist", 0.0))

                bucket["counts"]["vehicles_seen"] += total
                bucket["counts"]["emergency_seen"] += emergency
                bucket["counts"]["throughput_total"] += max(0.0, total - stopped)
                bucket["counts"]["throughput_emergency"] += max(0.0, emergency - min(emergency, stopped))

                bucket["wait_time_sec"]["vehicle_sum"] += avg_wait * stopped
                bucket["wait_time_sec"]["vehicle_count"] += stopped

                if emergency > 0:
                    # Approximation: emergency wait follows lane stopped wait profile.
                    em_stop = min(emergency, stopped)
                    bucket["wait_time_sec"]["emergency_sum"] += avg_wait * em_stop
                    bucket["wait_time_sec"]["emergency_count"] += em_stop

                bucket["speed"]["vehicle_speed_sum_mps"] += avg_speed * total
                bucket["speed"]["vehicle_speed_count"] += total

                try:
                    em_stops_lane = 0.0
                    for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
                        try:
                            veh_type = traci.vehicle.getTypeID(veh_id)
                            speed = float(traci.vehicle.getSpeed(veh_id))
                        except Exception:
                            continue
                        if veh_type not in {"ambulance", "police", "firetruck"}:
                            continue

                        is_stopped = speed < 0.1
                        was_stopped = bool(self._emergency_prev_stopped.get(veh_id, False))
                        if is_stopped and not was_stopped:
                            # Unique stop event: moving -> stopped transition.
                            em_stops_lane += 1.0
                        self._emergency_prev_stopped[veh_id] = is_stopped
                    bucket["quality"]["emergency_stops"] += em_stops_lane
                except Exception:
                    pass

                if edge_id in green_edges:
                    bucket["quality"]["green_total_sec"] += self.step_sec
                    if stopped <= 0.01:
                        bucket["quality"]["green_no_stopped_events"] += 1.0
                        bucket["quality"]["green_no_stopped_vehicle_sec"] += self.step_sec
                        bucket["quality"]["green_no_stopped_sec"] += self.step_sec

            ped_bucket = self._get_bucket(junction_id, "pedestrian", "pedestrian", lane_mode, fixed)
            p_waiting = float(live.get("pedestrians_waiting", 0.0))
            p_avg_wait = float(live.get("pedestrian_avg_wait_time", 0.0))
            p_total = float(live.get("pedestrians", 0.0))

            ped_bucket["counts"]["pedestrians_seen"] += p_total
            ped_bucket["wait_time_sec"]["pedestrian_sum"] += p_avg_wait * p_waiting
            ped_bucket["wait_time_sec"]["pedestrian_count"] += p_waiting
            ped_bucket["counts"]["throughput_total"] += max(0.0, p_total - p_waiting)

            if "J4_c0" in green_edges or "J4_c1" in green_edges:
                ped_bucket["quality"]["green_total_sec"] += self.step_sec
                if p_waiting <= 0.01:
                    ped_bucket["quality"]["green_no_stopped_events"] += 1.0
                    ped_bucket["quality"]["green_no_stopped_pedestrian_sec"] += self.step_sec
                    ped_bucket["quality"]["green_no_stopped_sec"] += self.step_sec

        # Keep only active emergency vehicles in transition memory.
        if self._emergency_prev_stopped:
            try:
                active_vehicle_ids = set(traci.vehicle.getIDList())
                stale_ids = set(self._emergency_prev_stopped.keys()) - active_vehicle_ids
                for veh_id in stale_ids:
                    self._emergency_prev_stopped.pop(veh_id, None)
            except Exception:
                pass

        if now_epoch - self.window_start_epoch >= self.window_sec:
            self.flush(now_epoch)

    @staticmethod
    def _safe_avg(numer: float, denom: float) -> float:
        return float(numer / denom) if denom > 0 else 0.0

    def flush(self, now_epoch: Optional[float] = None) -> None:
        if not self.enabled or self.collection is None or not self.acc:
            self.window_start_epoch = time.time()
            self._emergency_prev_stopped = {}
            return

        now_epoch = now_epoch or time.time()
        start_dt = datetime.fromtimestamp(self.window_start_epoch, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
        duration_sec = max(1.0, (end_dt - start_dt).total_seconds())

        docs: List[Dict[str, Any]] = []
        for bucket in self.acc.values():
            wt = bucket["wait_time_sec"]
            sp = bucket["speed"]

            docs.append(
                {
                    "schema_version": 1,
                    "doc_type": "lane_window",
                    "window": {
                        "start_ts": start_dt,
                        "end_ts": end_dt,
                        "duration_sec": float(duration_sec),
                    },
                    "mode": dict(bucket["mode"]),
                    "run": dict(bucket["run"]),
                    "location": dict(bucket["location"]),
                    "counts": {
                        "vehicles_seen": float(bucket["counts"]["vehicles_seen"]),
                        "emergency_seen": float(bucket["counts"]["emergency_seen"]),
                        "pedestrians_seen": float(bucket["counts"]["pedestrians_seen"]),
                        "throughput_total": float(bucket["counts"]["throughput_total"]),
                        "throughput_emergency": float(bucket["counts"]["throughput_emergency"]),
                    },
                    "wait_time_sec": {
                        "vehicle_avg": self._safe_avg(wt["vehicle_sum"], wt["vehicle_count"]),
                        "vehicle_sum": float(wt["vehicle_sum"]),
                        "emergency_avg": self._safe_avg(wt["emergency_sum"], wt["emergency_count"]),
                        "emergency_sum": float(wt["emergency_sum"]),
                        "pedestrian_avg": self._safe_avg(wt["pedestrian_sum"], wt["pedestrian_count"]),
                        "pedestrian_sum": float(wt["pedestrian_sum"]),
                    },
                    "speed": {
                        "vehicle_avg_mps": self._safe_avg(sp["vehicle_speed_sum_mps"], sp["vehicle_speed_count"]),
                        "vehicle_avg_kmph": self._safe_avg(sp["vehicle_speed_sum_mps"], sp["vehicle_speed_count"]) * 3.6,
                    },
                    "quality": {
                        "emergency_stops": float(bucket["quality"]["emergency_stops"]),
                        "green_no_stopped_events": float(bucket["quality"]["green_no_stopped_events"]),
                        "green_no_stopped_vehicle_sec": float(bucket["quality"].get("green_no_stopped_vehicle_sec", 0.0)),
                        "green_no_stopped_pedestrian_sec": float(bucket["quality"].get("green_no_stopped_pedestrian_sec", 0.0)),
                        "green_no_stopped_sec": float(bucket["quality"]["green_no_stopped_sec"]),
                        "green_total_sec": float(bucket["quality"]["green_total_sec"]),
                    },
                    "created_at": datetime.now(timezone.utc),
                }
            )

        try:
            self.collection.insert_many(docs, ordered=False)
        except Exception:
            pass

        self.acc = {}
        self.window_start_epoch = now_epoch
        self._emergency_prev_stopped = {}

    def _range_to_start(self, range_key: str) -> datetime:
        now = datetime.now(timezone.utc)
        ranges = {
            "3h": timedelta(hours=3),
            "6h": timedelta(hours=6),
            "1d": timedelta(days=1),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        return now - ranges.get(str(range_key), timedelta(hours=6))

    def query_summary(self, range_key: str, mode_variant: str = "all") -> Dict[str, Any]:
        if not self.enabled or self.collection is None:
            return {"range": range_key, "mode_variant": mode_variant, "rows": [], "total_docs": 0}

        start_dt = self._range_to_start(range_key)
        match: Dict[str, Any] = {
            "doc_type": "lane_window",
            "window.start_ts": {"$gte": start_dt},
        }
        if mode_variant and mode_variant != "all":
            match["mode.mode_variant"] = str(mode_variant)

        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": "$mode.mode_variant",
                    "docs": {"$sum": 1},
                    "duration_sec": {"$sum": "$window.duration_sec"},
                    "throughput_total": {"$sum": "$counts.throughput_total"},
                    "emergency_stops": {"$sum": "$quality.emergency_stops"},
                    "green_no_stopped_events": {"$sum": "$quality.green_no_stopped_events"},
                    "green_no_stopped_vehicle_sec": {"$sum": "$quality.green_no_stopped_vehicle_sec"},
                    "green_no_stopped_pedestrian_sec": {"$sum": "$quality.green_no_stopped_pedestrian_sec"},
                    "vehicle_wait_sum": {"$sum": "$wait_time_sec.vehicle_sum"},
                    "vehicle_wait_count": {"$sum": "$counts.vehicles_seen"},
                    "emergency_wait_sum": {"$sum": "$wait_time_sec.emergency_sum"},
                    "emergency_wait_count": {"$sum": "$counts.emergency_seen"},
                    "ped_wait_sum": {"$sum": "$wait_time_sec.pedestrian_sum"},
                    "ped_wait_count": {"$sum": "$counts.pedestrians_seen"},
                    "speed_kmph_sum": {"$sum": "$speed.vehicle_avg_kmph"},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        rows: List[Dict[str, Any]] = []
        total_docs = 0
        try:
            for rec in self.collection.aggregate(pipeline, allowDiskUse=True):
                docs = float(rec.get("docs", 0.0))
                total_docs += int(docs)
                duration = float(rec.get("duration_sec", 0.0))

                rows.append(
                    {
                        "mode_variant": str(rec.get("_id", "unknown")),
                        "average_wait_vehicle_sec": self._safe_avg(
                            float(rec.get("vehicle_wait_sum", 0.0)),
                            float(rec.get("vehicle_wait_count", 0.0)),
                        ),
                        "average_wait_emergency_sec": self._safe_avg(
                            float(rec.get("emergency_wait_sum", 0.0)),
                            float(rec.get("emergency_wait_count", 0.0)),
                        ),
                        "average_wait_pedestrian_sec": self._safe_avg(
                            float(rec.get("ped_wait_sum", 0.0)),
                            float(rec.get("ped_wait_count", 0.0)),
                        ),
                        "average_speed_vehicle_kmph": self._safe_avg(
                            float(rec.get("speed_kmph_sum", 0.0)),
                            docs,
                        ),
                        "emergency_vehicle_stops": float(rec.get("emergency_stops", 0.0)),
                        "green_no_stopped_events": float(rec.get("green_no_stopped_events", 0.0)),
                        "green_no_stopped_vehicle_sec": float(rec.get("green_no_stopped_vehicle_sec", 0.0)),
                        "green_no_stopped_pedestrian_sec": float(rec.get("green_no_stopped_pedestrian_sec", 0.0)),
                        "throughput_average_per_min": self._safe_avg(
                            float(rec.get("throughput_total", 0.0)) * 60.0,
                            duration,
                        ),
                        "sample_windows": int(docs),
                    }
                )
        except Exception:
            return {"range": range_key, "mode_variant": mode_variant, "rows": [], "total_docs": 0}

        return {
            "range": range_key,
            "mode_variant": mode_variant,
            "rows": rows,
            "total_docs": int(total_docs),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
