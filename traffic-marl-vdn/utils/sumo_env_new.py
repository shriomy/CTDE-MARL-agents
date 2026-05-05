import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import numpy as np
import sumolib
import traci

from data_injection.mongo_listener import MongoDBListener
from data_injection.vehicle_factory import SUMOVehicleFactory
from utils.traffic_actions import TrafficActions, TrafficLightSpec


class SumoEnv:
    """SUMO environment for centralized training with decentralized execution."""

    DEFAULT_VEHICLE_WEIGHTS = {
        "bike": 0.8,
        "real_car": 1.0,
        "car": 1.0,
        "auto": 1.2,
        "bus": 2.2,
        "truck": 2.4,
        "lorry": 2.5,
        "ambulance": 8.0,
        "police": 6.8,
        "firetruck": 8.2,
    }

    EMERGENCY_TYPES = {"ambulance", "police", "firetruck"}

    def __init__(self, config_path: str, use_gui: bool = False, env_config: Dict[str, Any] = None):
        self.config_path = config_path
        self.use_gui = use_gui
        self.env_config = env_config or {}

        self.sumo_cmd: List[str] = []
        self.episode_step = 0
        self.max_steps = int(self.env_config.get("max_steps_per_episode", 1800))

        self.top_k_lanes = int(self.env_config.get("top_k_lanes", 6))
        self.vehicle_weights = dict(self.DEFAULT_VEHICLE_WEIGHTS)
        self.vehicle_weights.update(self.env_config.get("vehicle_priority_weights", {}))
        self.pedestrian_wait_weights = {
            "elderly": 0.3,
            "mobility_aided": 0.4,
            "student": 0.1,
            "adult": 0.1,
        }
        self.pedestrian_wait_weights.update(self.env_config.get("pedestrian_wait_weights", {}))

        self.reward_weights = {
            # Positive rewards (ordered by importance)
            "no_emergency_stopped": 7.0,
            "throughput": 5.0,
            "priority_throughput": 6.0,
            # Negative rewards (ordered by importance)
            "empty_ped_green": 1.5,
            "avg_wait_emergency": 2.5,
            "avg_wait_vehicle": 1.0,
            "avg_wait_pedestrian_type": 0.2,
            "green_no_stopped": 2.0,
            "early_red_ped_crossing": 1.0,
        }
        self.reward_weights.update(self.env_config.get("reward_weights", {}))

        self.pedestrian_wait_edges = {
            "J4": {"E00", "-E0.80", "-E0", "E0"},
        }

        self.tl_ids: List[str] = []
        self.tl_specs: Dict[str, TrafficLightSpec] = {}
        self.incoming_lanes: Dict[str, List[str]] = {}
        self.incoming_edges: Dict[str, List[str]] = {}
        self.outgoing_lanes: Dict[str, List[str]] = {}
        self.pedestrian_controlled_edges: Dict[str, List[str]] = {}

        self.current_phase: Dict[str, int] = {}
        self.current_phase_duration: Dict[str, float] = {}

        self.prev_reward_snapshot: Dict[str, float] = {}
        self.prev_arrived_delta: float = 0.0
        self.vehicle_speed_sums: Dict[str, float] = {}
        self.vehicle_speed_samples: Dict[str, int] = {}

        # Episode diagnostics for training logs.
        self.episode_diag = {
            "green_change_drop": defaultdict(int),
            "green_change_checks": defaultdict(int),
            "ped_green_empty_count": defaultdict(int),
            "emergency_stopped_ids": defaultdict(set),
            "emergency_seen_outgoing_ids": defaultdict(set),
        }

        # Optional live injection from MongoDB during training.
        # Disabled when scenario files are used so training stays SUMO-only.
        self.use_scenario_files = bool(self.env_config.get("use_scenario_files", False))
        self.enable_data_injection = bool(self.env_config.get("enable_data_injection", False)) and not self.use_scenario_files
        self.mongo_listener = None
        self.vehicle_factory = None
        self.injection_poll_interval = float(self.env_config.get("injection_poll_interval", 1.0))
        self._last_injection_poll = 0.0

        self.scenario_config_path = self.env_config.get("scenario_config_path")

        self.state_dim = self._build_state_dim()

    @staticmethod
    def _normalize_ped_type_id(type_id: str) -> str:
        p_type = str(type_id or "").lower()
        if p_type in {"elder", "elderly"}:
            return "elderly"
        if p_type in {"mobility_aid", "mobility_aided", "mobility-aided"}:
            return "mobility_aided"
        if p_type == "student":
            return "student"
        return "adult"

    def _build_state_dim(self) -> int:
        lane_features = 5 * self.top_k_lanes
        aggregate_features = 9
        return lane_features + aggregate_features

    def start(self) -> None:
        """Start SUMO process and discover traffic-light topology."""
        sumo_binary = sumolib.checkBinary("sumo-gui" if self.use_gui else "sumo")
        self.sumo_cmd = [sumo_binary] + self._build_sumo_args()

        print(f"Starting SUMO with command: {' '.join(self.sumo_cmd)}")
        traci.start(self.sumo_cmd)
        time.sleep(1.5)

        self._discover_traffic_lights()
        self._build_default_specs()
        self._initialize_injection_if_enabled()
        print(f"SUMO started. Traffic lights: {self.tl_ids}")

    def close(self) -> None:
        """Close external resources and TraCI connection."""
        if self.mongo_listener is not None:
            try:
                self.mongo_listener.close()
            except Exception:
                pass
            self.mongo_listener = None

        try:
            traci.close()
            print("TraCI connection closed")
        except Exception:
            pass

    def _discover_traffic_lights(self) -> None:
        tl_ids = list(traci.trafficlight.getIDList())
        self.tl_ids = sorted(tl_ids)

        for tl_id in self.tl_ids:
            lanes = [l for l in traci.trafficlight.getControlledLanes(tl_id) if l and not l.startswith(":")]
            # Keep stable order while removing duplicates.
            dedup_lanes = list(dict.fromkeys(lanes))
            self.incoming_lanes[tl_id] = dedup_lanes
            self.incoming_edges[tl_id] = sorted({lane.split("_")[0] for lane in dedup_lanes if "_" in lane})

            ped_edges = set(self.pedestrian_wait_edges.get(tl_id, set()))
            for lane_id in traci.trafficlight.getControlledLanes(tl_id):
                if not lane_id:
                    continue
                try:
                    allowed = set(traci.lane.getAllowed(lane_id) or [])
                    disallowed = set(traci.lane.getDisallowed(lane_id) or [])
                    is_ped_accessible = ("pedestrian" in allowed) or (not allowed and "pedestrian" not in disallowed)
                    if is_ped_accessible:
                        edge_id = self._edge_from_lane_id(lane_id)
                        if edge_id:
                            ped_edges.add(edge_id)
                except Exception:
                    continue
            self.pedestrian_controlled_edges[tl_id] = sorted(ped_edges)

            outgoing = set()
            for lane_id in dedup_lanes:
                try:
                    links = traci.lane.getLinks(lane_id)
                    for link in links:
                        if link and len(link) > 0 and link[0]:
                            outgoing.add(link[0])
                except Exception:
                    continue
            self.outgoing_lanes[tl_id] = sorted(outgoing)

    @staticmethod
    def _edge_from_lane_id(lane_id: str) -> str:
        """Extract edge id from a SUMO lane id like E0_0 or :J4_w0_0."""
        if not lane_id or "_" not in lane_id:
            return ""
        return lane_id.rsplit("_", 1)[0]

    def _pedestrian_relevant_edges(self, tl_id: str) -> set:
        """Edges where pedestrians should be considered for a junction."""
        relevant_edges = set(self.pedestrian_wait_edges.get(tl_id, set()))
        relevant_edges.update(self.pedestrian_controlled_edges.get(tl_id, []))
        relevant_edges.update(self.incoming_edges.get(tl_id, []))
        return relevant_edges

    def _build_default_specs(self) -> None:
        """Build per-junction phase specs matching the provided 6/6/8 patterns."""
        for tl_id in self.tl_ids:
            if tl_id == "J1":
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green={0: 4, 1: 2, 2: 0},
                    green_to_yellow={0: 1, 2: 3, 4: 5},
                    yellow_to_next_green={1: 2, 3: 4, 5: 0},
                    yellow_phases={1, 3, 5},
                    pedestrian_green_phases=set(),
                    min_green=float(self.env_config.get("min_green_time", 20.0)),
                    max_green=float(self.env_config.get("max_green_time", 90.0)),
                    yellow_hold=float(self.env_config.get("yellow_time", 3.0)),
                    extension_step=float(self.env_config.get("green_extension", 5.0)),
                    min_ped_green=10.0,
                    max_ped_green=20.0,
                )
            elif tl_id == "J4":
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green={0: 0, 1: 2},
                    green_to_yellow={0: 1, 2: 1},
                    yellow_to_next_green={1: 0},
                    yellow_phases={1},
                    pedestrian_green_phases={2},
                    min_green=float(self.env_config.get("min_green_time", 20.0)),
                    max_green=float(self.env_config.get("max_green_time", 100.0)),
                    yellow_hold=float(self.env_config.get("yellow_time", 3.0)),
                    extension_step=float(self.env_config.get("green_extension", 5.0)),
                    min_ped_green=float(self.env_config.get("min_ped_green_time", 12.0)),
                    max_ped_green=float(self.env_config.get("max_ped_green_time", 45.0)),
                )
            elif tl_id == "J8":
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green={0: 0, 1: 6, 2: 2, 3: 4},
                    green_to_yellow={
                        0: [1, 8],
                        2: [3, 9],
                        4: 5,
                        6: 7,
                    },
                    yellow_to_next_green={
                        1: 2,
                        8: 4,
                        3: 4,
                        9: 6,
                        5: 6,
                        7: 0,
                    },
                    yellow_phases={1, 3, 5, 7, 8, 9},
                    pedestrian_green_phases=set(),
                    min_green=float(self.env_config.get("min_green_time", 20.0)),
                    max_green=float(self.env_config.get("max_green_time", 90.0)),
                    yellow_hold=float(self.env_config.get("yellow_time", 3.0)),
                    extension_step=float(self.env_config.get("green_extension", 5.0)),
                    min_ped_green=10.0,
                    max_ped_green=20.0,
                )
            else:
                phase_count = len(traci.trafficlight.getAllProgramLogics(tl_id)[0].phases)
                even_green = [i for i in range(phase_count) if i % 2 == 0]
                action_to_green = {a: even_green[min(a, len(even_green) - 1)] for a in range(4)}
                green_to_yellow = {g: min(g + 1, phase_count - 1) for g in even_green}
                yellow_to_next_green = {y: min(y + 1, phase_count - 1) for y in range(1, phase_count, 2)}
                yellow_phases = {y for y in range(phase_count) if y not in even_green}
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green=action_to_green,
                    green_to_yellow=green_to_yellow,
                    yellow_to_next_green=yellow_to_next_green,
                    yellow_phases=yellow_phases,
                    pedestrian_green_phases=set(),
                    min_green=float(self.env_config.get("min_green_time", 20.0)),
                    max_green=float(self.env_config.get("max_green_time", 90.0)),
                    yellow_hold=float(self.env_config.get("yellow_time", 3.0)),
                    extension_step=float(self.env_config.get("green_extension", 5.0)),
                    min_ped_green=10.0,
                    max_ped_green=20.0,
                )

        self.current_phase = {tl_id: int(traci.trafficlight.getPhase(tl_id)) for tl_id in self.tl_ids}
        self.current_phase_duration = {tl_id: 0.0 for tl_id in self.tl_ids}

    def _initialize_injection_if_enabled(self) -> None:
        if not self.enable_data_injection:
            return
        self.mongo_listener = MongoDBListener(
            connection_string=self.env_config.get(
                "mongo_uri",
                "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
            ),
            poll_interval=self.injection_poll_interval,
        )
        self.vehicle_factory = SUMOVehicleFactory()
        self._last_injection_poll = time.monotonic()

    def set_scenario_config(self, scenario_config_path: str) -> None:
        """Set the scenario SUMO config used when reloading SUMO for the next episode."""
        self.scenario_config_path = scenario_config_path
        if scenario_config_path:
            self.enable_data_injection = False

    def _build_sumo_args(self) -> List[str]:
        """Build SUMO command args, optionally overriding the route file.

        This keeps marl_config.json as the single settings source while allowing
        episode-specific SUMO route files to be selected from generated scenarios.
        """
        args = [
            "-c",
            self.config_path,
            "--start",
            "--quit-on-end",
            "--step-length",
            "1",
            "--no-warnings",
        ]

        config_path = self.scenario_config_path or self.config_path
        candidates = [config_path]
        if not os.path.isabs(config_path):
            candidates.append(os.path.normpath(os.path.join(os.path.dirname(self.config_path), config_path)))
            candidates.append(os.path.normpath(os.path.join(os.path.dirname(self.config_path), "..", config_path)))

        for candidate in candidates:
            if os.path.exists(candidate):
                config_path = candidate
                break

        args[1] = config_path
        return args

    def reset(self) -> Dict[str, np.ndarray]:
        self.sumo_cmd = self._build_sumo_args()
        traci.load(self.sumo_cmd)
        self.episode_step = 0
        self.prev_reward_snapshot = self._reward_snapshot()
        self.prev_arrived_delta = 0.0
        self.current_phase = {tl_id: int(traci.trafficlight.getPhase(tl_id)) for tl_id in self.tl_ids}
        self.current_phase_duration = {tl_id: 0.0 for tl_id in self.tl_ids}
        self.episode_diag = {
            "green_change_drop": defaultdict(int),
            "green_change_checks": defaultdict(int),
            "ped_green_empty_count": defaultdict(int),
            "emergency_stopped_ids": defaultdict(set),
            "emergency_seen_outgoing_ids": defaultdict(set),
        }
        self.vehicle_speed_sums = {}
        self.vehicle_speed_samples = {}
        return self.get_state()

    def _update_vehicle_speed_history(self) -> None:
        """Track per-vehicle historical speed so lane Avg Speed reflects full lane stay."""
        active_ids = set(traci.vehicle.getIDList())

        for veh_id in active_ids:
            try:
                speed = float(traci.vehicle.getSpeed(veh_id))
            except Exception:
                continue
            self.vehicle_speed_sums[veh_id] = float(self.vehicle_speed_sums.get(veh_id, 0.0)) + speed
            self.vehicle_speed_samples[veh_id] = int(self.vehicle_speed_samples.get(veh_id, 0)) + 1

        stale_ids = set(self.vehicle_speed_sums.keys()) - active_ids
        for veh_id in stale_ids:
            self.vehicle_speed_sums.pop(veh_id, None)
            self.vehicle_speed_samples.pop(veh_id, None)

    def _vehicle_historical_avg_speed(self, veh_id: str) -> float:
        samples = int(self.vehicle_speed_samples.get(veh_id, 0))
        if samples <= 0:
            return 0.0
        return float(self.vehicle_speed_sums.get(veh_id, 0.0) / samples)

    def _lane_live_metrics(self, lane_id: str) -> Dict[str, float]:
        """Exact lane metrics used for both training diagnostics and dashboard telemetry."""
        vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
        total_vehicles = float(len(vehicle_ids))
        stopped_vehicles = 0.0
        stopped_wait_sum = 0.0
        weighted_sum_all = 0.0
        emergency_total = 0.0
        lane_hist_speed_sum = 0.0

        for veh_id in vehicle_ids:
            speed = float(traci.vehicle.getSpeed(veh_id))
            veh_type = traci.vehicle.getTypeID(veh_id)
            weight = float(self.vehicle_weights.get(veh_type, 1.0))
            is_emergency = veh_type in self.EMERGENCY_TYPES

            weighted_sum_all += weight
            lane_hist_speed_sum += self._vehicle_historical_avg_speed(veh_id)

            if is_emergency:
                emergency_total += 1.0
            if speed < 0.1:
                stopped_vehicles += 1.0
                stopped_wait_sum += float(traci.vehicle.getWaitingTime(veh_id))

        avg_wait_stopped = (stopped_wait_sum / stopped_vehicles) if stopped_vehicles > 0 else 0.0
        vehicle_density = (weighted_sum_all / total_vehicles) if total_vehicles > 0 else 0.0
        lane_avg_speed_hist = (lane_hist_speed_sum / total_vehicles) if total_vehicles > 0 else 0.0

        return {
            "total_vehicles": total_vehicles,
            "stopped_vehicles": stopped_vehicles,
            "stopped_wait_sum": stopped_wait_sum,
            "avg_wait_stopped": avg_wait_stopped,
            "weighted_sum_all": weighted_sum_all,
            "vehicle_density": vehicle_density,
            "emergency_total": emergency_total,
            "avg_speed_hist": lane_avg_speed_hist,
        }

    def _collect_junction_live_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Exact per-junction metrics based on upstream lanes for telemetry and training checks."""
        out: Dict[str, Dict[str, Any]] = {}

        for tl_id in self.tl_ids:
            lane_metrics: Dict[str, Dict[str, float]] = {}
            vehicles_waiting = 0.0
            stopped_wait_sum = 0.0
            weighted_sum_all = 0.0
            total_vehicles_all = 0.0
            emergency_total = 0.0
            lane_counts = []
            lane_counts_by_edge: Dict[str, int] = {}

            for lane_id in self.incoming_lanes.get(tl_id, []):
                metrics = self._lane_live_metrics(lane_id)
                lane_metrics[lane_id] = metrics

                vehicles_waiting += metrics["stopped_vehicles"]
                stopped_wait_sum += metrics["stopped_wait_sum"]
                weighted_sum_all += metrics["weighted_sum_all"]
                total_vehicles_all += metrics["total_vehicles"]
                emergency_total += metrics["emergency_total"]

                q_len = int(round(metrics["total_vehicles"]))
                lane_counts.append(q_len)
                edge_id = lane_id.split("_")[0] if "_" in lane_id else lane_id
                lane_counts_by_edge[edge_id] = int(lane_counts_by_edge.get(edge_id, 0)) + q_len

            avg_wait_time = (stopped_wait_sum / vehicles_waiting) if vehicles_waiting > 0 else 0.0
            vehicle_density = (weighted_sum_all / total_vehicles_all) if total_vehicles_all > 0 else 0.0
            ped_waiting_count, ped_wait_total, ped_avg_wait = self._pedestrian_wait_metrics_for_tl(tl_id)
            pedestrian_types = self._count_person_types_for_tl(tl_id)

            out[tl_id] = {
                "vehicles_waiting": float(vehicles_waiting),
                "avg_wait_time": float(avg_wait_time),
                "vehicle_density": float(vehicle_density),
                "emergency": int(round(emergency_total)),
                "pedestrians": int(self._count_persons_for_tl(tl_id)),
                "pedestrians_waiting": int(ped_waiting_count),
                "pedestrian_wait_total": float(ped_wait_total),
                "pedestrian_avg_wait_time": float(ped_avg_wait),
                "pedestrian_types": pedestrian_types,
                "lane_metrics": lane_metrics,
                "lane_counts": lane_counts,
                "lane_counts_by_edge": lane_counts_by_edge,
            }

        return out

    def _count_persons_for_tl(self, tl_id: str) -> int:
        """Count pedestrians relevant to a junction using known crossing and incoming edges."""
        relevant_edges = self._pedestrian_relevant_edges(tl_id)

        count = 0
        for person_id in traci.person.getIDList():
            try:
                if traci.person.getRoadID(person_id) in relevant_edges:
                    count += 1
            except Exception:
                continue
        return count

    def _count_person_types_for_tl(self, tl_id: str) -> Dict[str, int]:
        """Count relevant pedestrians by type for junction telemetry."""
        relevant_edges = self._pedestrian_relevant_edges(tl_id)

        out = {
            "elderly": 0,
            "mobility_aided": 0,
            "student": 0,
            "adult": 0,
        }

        for person_id in traci.person.getIDList():
            try:
                if traci.person.getRoadID(person_id) not in relevant_edges:
                    continue
                ped_type = self._normalize_ped_type_id(traci.person.getTypeID(person_id))
                out[ped_type] += 1
            except Exception:
                continue

        return out

    def _pedestrian_wait_metrics_for_tl(self, tl_id: str) -> Tuple[int, float, float]:
        """Return waiting pedestrians count, total wait and average wait for a junction."""
        relevant_edges = self._pedestrian_relevant_edges(tl_id)
        waiting_count = 0
        total_wait = 0.0

        for person_id in traci.person.getIDList():
            try:
                if traci.person.getRoadID(person_id) not in relevant_edges:
                    continue
                speed = float(traci.person.getSpeed(person_id))
                if speed < 0.05:
                    waiting_count += 1
                    total_wait += float(traci.person.getWaitingTime(person_id))
            except Exception:
                continue

        avg_wait = (total_wait / waiting_count) if waiting_count > 0 else 0.0
        return waiting_count, total_wait, avg_wait

    def _count_pedestrians_crossing_for_tl(self, tl_id: str) -> int:
        """Count pedestrians currently on crossing edges of this junction."""
        crossing_prefix = f":{tl_id}_c"
        count = 0
        for person_id in traci.person.getIDList():
            try:
                road_id = str(traci.person.getRoadID(person_id) or "")
                if road_id.startswith(crossing_prefix):
                    count += 1
            except Exception:
                continue
        return count

    def _collect_junction_diagnostics(
        self,
        step_meta: Dict[str, Dict[str, float]],
        arrived_delta: float,
    ) -> Dict[str, Dict[str, Any]]:
        """Collect per-junction metrics required for episode training logs."""
        out: Dict[str, Dict[str, Any]] = {}

        for tl_id in self.tl_ids:
            emergency_by_lane: Dict[str, int] = {}
            normal_by_lane: Dict[str, int] = {}
            lane_priority_score: Dict[str, float] = {}
            emergency_stops = 0

            for lane_id in self.incoming_lanes.get(tl_id, []):
                emergency_count_lane = 0
                normal_count_lane = 0
                lane_priority = 0.0
                for veh_id in traci.lane.getLastStepVehicleIDs(lane_id):
                    veh_type = traci.vehicle.getTypeID(veh_id)
                    speed = traci.vehicle.getSpeed(veh_id)
                    is_emergency = veh_type in self.EMERGENCY_TYPES

                    lane_priority += float(self.vehicle_weights.get(veh_type, 1.0))
                    if is_emergency:
                        emergency_count_lane += 1
                        if speed < 0.1:
                            emergency_stops += 1
                            self.episode_diag["emergency_stopped_ids"][tl_id].add(veh_id)
                    else:
                        normal_count_lane += 1

                emergency_by_lane[lane_id] = emergency_count_lane
                normal_by_lane[lane_id] = normal_count_lane
                lane_priority_score[lane_id] = lane_priority

            for out_lane in self.outgoing_lanes.get(tl_id, []):
                for veh_id in traci.lane.getLastStepVehicleIDs(out_lane):
                    try:
                        if traci.vehicle.getTypeID(veh_id) in self.EMERGENCY_TYPES:
                            self.episode_diag["emergency_seen_outgoing_ids"][tl_id].add(veh_id)
                    except Exception:
                        continue

            ped_count = self._count_persons_for_tl(tl_id)
            ped_empty_green = 0
            meta = step_meta.get(tl_id, {})
            if meta.get("is_ped_green", 0.0) > 0.5 and ped_count <= 0:
                ped_empty_green = 1
                self.episode_diag["ped_green_empty_count"][tl_id] += 1

            if meta.get("switched", 0.0) > 0.5:
                self.episode_diag["green_change_checks"][tl_id] += 1
                if arrived_delta < self.prev_arrived_delta:
                    self.episode_diag["green_change_drop"][tl_id] += 1

            most_priority_lane = ""
            if lane_priority_score:
                most_priority_lane = max(lane_priority_score, key=lane_priority_score.get)

            stopped_ids = self.episode_diag["emergency_stopped_ids"][tl_id]
            outgoing_ids = self.episode_diag["emergency_seen_outgoing_ids"][tl_id]
            passed_without_stop = len(outgoing_ids - stopped_ids)

            checks = self.episode_diag["green_change_checks"][tl_id]
            drops = self.episode_diag["green_change_drop"][tl_id]
            drop_rate = float(drops / checks) if checks > 0 else 0.0

            out[tl_id] = {
                "emergency_detected_by_lane": emergency_by_lane,
                "normal_detected_by_lane": normal_by_lane,
                "pedestrians_detected": ped_count,
                "green_change_left_vehicle_drop_rate": drop_rate,
                "green_change_checks": checks,
                "green_change_drops": drops,
                "emergency_stops": emergency_stops,
                "emergency_passed_without_stop": passed_without_stop,
                "most_priority_lane": most_priority_lane,
                "ped_green_when_empty_step": ped_empty_green,
                "ped_green_when_empty_total": self.episode_diag["ped_green_empty_count"][tl_id],
            }

        self.prev_arrived_delta = arrived_delta
        return out

    def _lane_wait_features(self, lane_id: str) -> Tuple[float, float, float, float, float, float]:
        metrics = self._lane_live_metrics(lane_id)
        queue = float(metrics["stopped_vehicles"])
        total_wait = float(metrics["stopped_wait_sum"])
        avg_wait = float(metrics["avg_wait_stopped"])
        priority_score = float(metrics["weighted_sum_all"])
        emergency_count = float(metrics["emergency_total"])
        emergency_stopped = 0.0
        return queue, total_wait, avg_wait, priority_score, emergency_count, emergency_stopped

    def _pedestrian_wait_pressure(self, tl_id: str) -> float:
        waiting_count, total_wait, _ = self._pedestrian_wait_metrics_for_tl(tl_id)
        if waiting_count <= 0:
            return 0.0
        return total_wait

    def get_state(self) -> Dict[str, np.ndarray]:
        """Build local observations per intersection with priority-aware queue features."""
        state: Dict[str, np.ndarray] = {}

        for tl_id in self.tl_ids:
            lane_vectors = []
            total_queue = 0.0
            total_wait = 0.0
            total_priority = 0.0
            total_emergency = 0.0
            total_emergency_stopped = 0.0
            total_vehicle_count = 0.0

            for lane_id in self.incoming_lanes.get(tl_id, []):
                q, t_wait, avg_wait, p_score, emg_cnt, emg_stop = self._lane_wait_features(lane_id)
                total_queue += q
                total_wait += t_wait
                total_priority += p_score
                total_emergency += emg_cnt
                total_emergency_stopped += emg_stop
                total_vehicle_count += float(len(traci.lane.getLastStepVehicleIDs(lane_id)))
                lane_vectors.append((lane_id, q, t_wait, avg_wait, p_score, emg_cnt))

            lane_vectors.sort(key=lambda x: x[4], reverse=True)
            lane_features: List[float] = []
            for _, q, t_wait, avg_wait, p_score, emg_cnt in lane_vectors[: self.top_k_lanes]:
                lane_features.extend(
                    [
                        min(q / 20.0, 1.0),
                        min(t_wait / 180.0, 1.0),
                        min(avg_wait / 60.0, 1.0),
                        min(p_score / 30.0, 1.0),
                        min(emg_cnt / 10.0, 1.0),
                    ]
                )

            expected_len = self.top_k_lanes * 5
            if len(lane_features) < expected_len:
                lane_features.extend([0.0] * (expected_len - len(lane_features)))

            current_phase = int(traci.trafficlight.getPhase(tl_id))
            self.current_phase[tl_id] = current_phase
            try:
                spent = float(traci.trafficlight.getSpentDuration(tl_id))
            except Exception:
                spent = float(traci.trafficlight.getPhaseDuration(tl_id))
            self.current_phase_duration[tl_id] = spent

            ped_wait = self._pedestrian_wait_pressure(tl_id)
            is_yellow = 1.0 if current_phase in self.tl_specs[tl_id].yellow_phases else 0.0
            is_ped_green = 1.0 if current_phase in self.tl_specs[tl_id].pedestrian_green_phases else 0.0

            agg_features = [
                min(total_queue / 100.0, 1.0),
                min(total_wait / 600.0, 1.0),
                min((total_wait / max(total_queue, 1.0)) / 90.0, 1.0),
                min((total_priority / max(total_vehicle_count, 1.0)) / 8.0, 1.0),
                min(total_emergency / 20.0, 1.0),
                min(total_emergency_stopped / 20.0, 1.0),
                min(ped_wait / 180.0, 1.0),
                is_yellow,
                is_ped_green,
            ]

            state_vec = np.asarray(lane_features + agg_features, dtype=np.float32)
            state[tl_id] = state_vec

        return state

    def _reward_snapshot(self) -> Dict[str, float]:
        """Snapshot counters used for delta-based reward shaping."""
        waiting_normal = 0.0
        waiting_emergency = 0.0
        stopped_normal = 0.0
        stopped_emergency = 0.0
        vehicle_count_normal = 0.0
        vehicle_count_emergency = 0.0

        for veh_id in traci.vehicle.getIDList():
            veh_type = traci.vehicle.getTypeID(veh_id)
            wait_t = traci.vehicle.getWaitingTime(veh_id)
            is_stopped = traci.vehicle.getSpeed(veh_id) < 0.1
            if veh_type in self.EMERGENCY_TYPES:
                waiting_emergency += wait_t
                vehicle_count_emergency += 1.0
                stopped_emergency += 1.0 if is_stopped else 0.0
            else:
                waiting_normal += wait_t
                vehicle_count_normal += 1.0
                stopped_normal += 1.0 if is_stopped else 0.0

        ped_wait = 0.0
        ped_stopped = 0.0
        ped_wait_sum_by_type = {
            "elderly": 0.0,
            "mobility_aided": 0.0,
            "student": 0.0,
            "adult": 0.0,
        }
        ped_wait_count_by_type = {
            "elderly": 0.0,
            "mobility_aided": 0.0,
            "student": 0.0,
            "adult": 0.0,
        }
        for person_id in traci.person.getIDList():
            try:
                wt = traci.person.getWaitingTime(person_id)
                ped_wait += wt
                if traci.person.getSpeed(person_id) < 0.05:
                    ped_stopped += 1.0
                    ped_type = self._normalize_ped_type_id(traci.person.getTypeID(person_id))
                    ped_wait_sum_by_type[ped_type] += wt
                    ped_wait_count_by_type[ped_type] += 1.0
            except Exception:
                continue

        # Arrivals is the right throughput signal for "vehicles left the network".
        departed = float(traci.simulation.getArrivedNumber())
        arrived_priority = 0.0
        for veh_id in traci.simulation.getArrivedIDList():
            try:
                veh_type = traci.vehicle.getTypeID(veh_id)
                arrived_priority += float(self.vehicle_weights.get(veh_type, 1.0))
            except Exception:
                # Vehicle can be removed before variable lookup in the same step.
                continue

        avg_wait_emergency = waiting_emergency / vehicle_count_emergency if vehicle_count_emergency > 0 else 0.0
        total_vehicles = vehicle_count_normal + vehicle_count_emergency
        avg_wait_vehicle = (waiting_normal + waiting_emergency) / total_vehicles if total_vehicles > 0 else 0.0

        ped_avg_wait_by_type = {}
        for ped_type in ped_wait_sum_by_type:
            denom = ped_wait_count_by_type[ped_type]
            ped_avg_wait_by_type[ped_type] = (ped_wait_sum_by_type[ped_type] / denom) if denom > 0 else 0.0

        return {
            "waiting_normal": waiting_normal,
            "waiting_emergency": waiting_emergency,
            "stopped_normal": stopped_normal,
            "stopped_emergency": stopped_emergency,
            "ped_wait": ped_wait,
            "ped_stopped": ped_stopped,
            "arrived": departed,
            "arrived_priority": arrived_priority,
            "avg_wait_emergency": avg_wait_emergency,
            "avg_wait_vehicle": avg_wait_vehicle,
            "ped_avg_wait_elderly": ped_avg_wait_by_type["elderly"],
            "ped_avg_wait_mobility_aided": ped_avg_wait_by_type["mobility_aided"],
            "ped_avg_wait_student": ped_avg_wait_by_type["student"],
            "ped_avg_wait_adult": ped_avg_wait_by_type["adult"],
        }

    def get_reward(self, step_meta: Dict[str, Dict[str, float]]) -> Tuple[float, Dict[str, float]]:
        """Global reward aligned with emergency-first and pedestrian-aware priorities."""
        snap = self._reward_snapshot()
        prev = self.prev_reward_snapshot or snap
        throughput = max(0.0, snap["arrived"] - prev["arrived"])
        priority_throughput = max(0.0, snap["arrived_priority"])

        # Penalty: pedestrian green with no pedestrians waiting.
        empty_ped_green_penalty = 0.0
        for tl_id, meta in step_meta.items():
            if meta.get("is_ped_green", 0.0) > 0.5 and meta.get("ped_count", 0.0) <= 0.01:
                empty_ped_green_penalty += 1.0

        green_with_no_stopped_penalty = 0.0
        for tl_id, meta in step_meta.items():
            if meta.get("switched", 0.0) > 0.5 and meta.get("is_yellow", 0.0) <= 0.5 and meta.get("stopped_incoming", 0.0) <= 0.01:
                green_with_no_stopped_penalty += 1.0

        early_red_ped_crossing_penalty = 0.0
        for _, meta in step_meta.items():
            if meta.get("ped_crossing_cut", 0.0) > 0.5:
                early_red_ped_crossing_penalty += 1.0

        ped_type_wait_penalty = (
            self.pedestrian_wait_weights.get("elderly", 1.0) * snap["ped_avg_wait_elderly"]
            + self.pedestrian_wait_weights.get("mobility_aided", 1.0) * snap["ped_avg_wait_mobility_aided"]
            + self.pedestrian_wait_weights.get("student", 1.0) * snap["ped_avg_wait_student"]
            + self.pedestrian_wait_weights.get("adult", 1.0) * snap["ped_avg_wait_adult"]
        )

        no_emergency_stop_bonus = 1.0 if snap["stopped_emergency"] <= 0 else 0.0

        reward_components = {
            "no_emergency_stop_bonus": self.reward_weights["no_emergency_stopped"] * no_emergency_stop_bonus,
            "throughput_bonus": self.reward_weights["throughput"] * throughput,
            "priority_throughput_bonus": self.reward_weights["priority_throughput"] * priority_throughput,
            "empty_ped_green_penalty": -self.reward_weights["empty_ped_green"] * empty_ped_green_penalty,
            "avg_wait_emergency_penalty": -self.reward_weights["avg_wait_emergency"] * snap["avg_wait_emergency"],
            "avg_wait_vehicle_penalty": -self.reward_weights["avg_wait_vehicle"] * snap["avg_wait_vehicle"],
            "avg_wait_pedestrian_type_penalty": -self.reward_weights["avg_wait_pedestrian_type"] * ped_type_wait_penalty,
            "green_no_stopped_penalty": -self.reward_weights["green_no_stopped"] * green_with_no_stopped_penalty,
            "early_red_ped_crossing_penalty": -self.reward_weights["early_red_ped_crossing"] * early_red_ped_crossing_penalty,
        }

        reward = float(sum(reward_components.values()))
        self.prev_reward_snapshot = snap
        return reward, reward_components

    def _inject_live_records(self) -> Dict[str, int]:
        stats = {"emergency": 0, "normal": 0, "pedestrian": 0}
        if not self.enable_data_injection or self.mongo_listener is None or self.vehicle_factory is None:
            return stats

        now = time.monotonic()
        if now - self._last_injection_poll < self.injection_poll_interval:
            return stats
        self._last_injection_poll = now

        records = self.mongo_listener.get_new_records()
        for record in records:
            r_type = record.get("type")
            if r_type == "emergency_vehicle":
                if self.vehicle_factory.create_emergency_vehicle(record):
                    stats["emergency"] += 1
            elif r_type == "normal_vehicle":
                created = self.vehicle_factory.create_normal_vehicles(record)
                stats["normal"] += len(created)
            elif r_type == "pedestrian":
                created = self.vehicle_factory.create_pedestrians(record)
                stats["pedestrian"] += len(created)
        return stats

    def step(
        self,
        actions: Dict[str, int],
        ignore_timing_for: Dict[str, bool] = None,
    ) -> Tuple[Dict[str, np.ndarray], float, bool, Dict[str, Any]]:
        """Apply joint action, advance simulation, and return next state and global reward."""
        step_meta: Dict[str, Dict[str, float]] = {}
        ignore_timing_for = ignore_timing_for or {}

        for tl_id, action in actions.items():
            spec = self.tl_specs[tl_id]
            phase_before = int(traci.trafficlight.getPhase(tl_id))
            ped_crossing_before = float(self._count_pedestrians_crossing_for_tl(tl_id))
            force_ped_extension = (
                phase_before in spec.pedestrian_green_phases and ped_crossing_before > 0.0
            )
            transition = TrafficActions.execute_action(
                tl_id,
                int(action),
                spec,
                ignore_timing_rules=bool(ignore_timing_for.get(tl_id, False)),
                force_pedestrian_extension=force_ped_extension,
            )
            new_phase = int(transition["new_phase"])
            current_phase = int(traci.trafficlight.getPhase(tl_id))
            ped_crossing_cut = (
                1.0
                if (phase_before in spec.pedestrian_green_phases and new_phase != phase_before and ped_crossing_before > 0.0)
                else 0.0
            )

            step_meta[tl_id] = {
                "action": float(action),
                "phase": float(current_phase),
                "new_phase": float(new_phase),
                "is_yellow": 1.0 if current_phase in spec.yellow_phases else 0.0,
                "is_ped_green": 1.0 if current_phase in spec.pedestrian_green_phases else 0.0,
                "ped_wait": self._pedestrian_wait_pressure(tl_id),
                "ped_count": float(self._count_persons_for_tl(tl_id)),
                "ped_crossing": ped_crossing_before,
                "ped_crossing_cut": ped_crossing_cut,
                "stopped_incoming": float(sum(traci.lane.getLastStepHaltingNumber(l) for l in self.incoming_lanes.get(tl_id, []))),
                "switched": float(transition["switched"]),
            }

        injection_stats = self._inject_live_records()

        traci.simulationStep()
        self.episode_step += 1
        self._update_vehicle_speed_history()

        snapshot_now = self._reward_snapshot()
        snapshot_prev = self.prev_reward_snapshot or snapshot_now
        arrived_delta = max(0.0, snapshot_now["arrived"] - snapshot_prev["arrived"])

        next_state = self.get_state()
        reward, reward_components = self.get_reward(step_meta)
        junction_diagnostics = self._collect_junction_diagnostics(step_meta, arrived_delta)
        junction_live_metrics = self._collect_junction_live_metrics()
        done = self.episode_step >= self.max_steps

        vehicle_ids = traci.vehicle.getIDList()
        avg_speed = float(np.mean([traci.vehicle.getSpeed(v) for v in vehicle_ids])) if vehicle_ids else 0.0

        info = {
            "step": self.episode_step,
            "vehicle_count": len(vehicle_ids),
            "avg_speed": avg_speed,
            "reward_components": reward_components,
            "step_meta": step_meta,
            "injection_stats": injection_stats,
            "junction_diagnostics": junction_diagnostics,
            "junction_live_metrics": junction_live_metrics,
        }

        return next_state, reward, done, info
