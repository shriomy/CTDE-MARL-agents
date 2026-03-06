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
        "ambulance": 4.0,
        "police": 3.8,
        "firetruck": 4.2,
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

        self.pedestrian_wait_edges = {
            "J4": {"E00", "-E0.80", "-E0", "E0"},
        }

        self.tl_ids: List[str] = []
        self.tl_specs: Dict[str, TrafficLightSpec] = {}
        self.incoming_lanes: Dict[str, List[str]] = {}
        self.incoming_edges: Dict[str, List[str]] = {}
        self.outgoing_lanes: Dict[str, List[str]] = {}

        self.current_phase: Dict[str, int] = {}
        self.current_phase_duration: Dict[str, float] = {}

        self.prev_reward_snapshot: Dict[str, float] = {}
        self.prev_arrived_delta: float = 0.0

        # Episode diagnostics for training logs.
        self.episode_diag = {
            "green_change_drop": defaultdict(int),
            "green_change_checks": defaultdict(int),
            "ped_green_empty_count": defaultdict(int),
            "emergency_stopped_ids": defaultdict(set),
            "emergency_seen_outgoing_ids": defaultdict(set),
        }

        # Optional live injection from MongoDB during training.
        self.enable_data_injection = bool(self.env_config.get("enable_data_injection", False))
        self.mongo_listener = None
        self.vehicle_factory = None
        self.injection_poll_interval = float(self.env_config.get("injection_poll_interval", 1.0))
        self._last_injection_poll = 0.0

        self.state_dim = self._build_state_dim()

    def _build_state_dim(self) -> int:
        lane_features = 5 * self.top_k_lanes
        aggregate_features = 9
        return lane_features + aggregate_features

    def start(self) -> None:
        """Start SUMO process and discover traffic-light topology."""
        sumo_binary = sumolib.checkBinary("sumo-gui" if self.use_gui else "sumo")
        self.sumo_cmd = [sumo_binary, "-c", self.config_path]
        self.sumo_cmd.extend([
            "--start",
            "--quit-on-end",
            "--step-length",
            "1",
            "--no-warnings",
        ])

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

    def _build_default_specs(self) -> None:
        """Build per-junction phase specs matching the provided 6/6/8 patterns."""
        for tl_id in self.tl_ids:
            if tl_id == "J1":
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green={0: 0, 1: 2, 2: 4, 3: 4},
                    green_to_yellow={0: 1, 2: 3, 4: 5},
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
                    action_to_green={0: 0, 1: 3, 2: 0, 3: 3},
                    green_to_yellow={0: 1, 3: 4},
                    yellow_phases={1, 2, 4, 5},
                    pedestrian_green_phases={3},
                    min_green=float(self.env_config.get("min_green_time", 20.0)),
                    max_green=float(self.env_config.get("max_green_time", 100.0)),
                    yellow_hold=float(self.env_config.get("yellow_time", 3.0)),
                    extension_step=float(self.env_config.get("green_extension", 5.0)),
                    min_ped_green=float(self.env_config.get("min_ped_green_time", 12.0)),
                    max_ped_green=float(self.env_config.get("max_ped_green_time", 45.0)),
                )
            elif tl_id == "J8":
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green={0: 0, 1: 2, 2: 4, 3: 6},
                    green_to_yellow={0: 1, 2: 3, 4: 5, 6: 7},
                    yellow_phases={1, 3, 5, 7},
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
                yellow_phases = {y for y in range(phase_count) if y not in even_green}
                self.tl_specs[tl_id] = TrafficLightSpec(
                    action_to_green=action_to_green,
                    green_to_yellow=green_to_yellow,
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

    def reset(self) -> Dict[str, np.ndarray]:
        traci.load(self.sumo_cmd[1:])
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
        return self.get_state()

    def _count_persons_for_tl(self, tl_id: str) -> int:
        """Count pedestrians relevant to a junction using known crossing and incoming edges."""
        relevant_edges = set(self.pedestrian_wait_edges.get(tl_id, set()))
        relevant_edges.update(self.incoming_edges.get(tl_id, []))

        count = 0
        for person_id in traci.person.getIDList():
            try:
                if traci.person.getRoadID(person_id) in relevant_edges:
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
        vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
        queue = 0.0
        total_wait = 0.0
        priority_score = 0.0
        emergency_count = 0.0
        emergency_stopped = 0.0

        for veh_id in vehicle_ids:
            speed = traci.vehicle.getSpeed(veh_id)
            veh_type = traci.vehicle.getTypeID(veh_id)
            weight = self.vehicle_weights.get(veh_type, 1.0)
            is_emergency = veh_type in self.EMERGENCY_TYPES

            if speed < 0.1:
                queue += 1.0
                wait_t = traci.vehicle.getWaitingTime(veh_id)
                total_wait += wait_t
                priority_score += weight
                if is_emergency:
                    emergency_stopped += 1.0
            if is_emergency:
                emergency_count += 1.0

        avg_wait = (total_wait / queue) if queue > 0 else 0.0
        return queue, total_wait, avg_wait, priority_score, emergency_count, emergency_stopped

    def _pedestrian_wait_pressure(self, tl_id: str) -> float:
        if tl_id not in self.pedestrian_wait_edges:
            return 0.0

        relevant_edges = self.pedestrian_wait_edges[tl_id]
        total_wait = 0.0
        for person_id in traci.person.getIDList():
            try:
                edge_id = traci.person.getRoadID(person_id)
                speed = traci.person.getSpeed(person_id)
                if edge_id in relevant_edges and speed < 0.05:
                    total_wait += traci.person.getWaitingTime(person_id)
            except Exception:
                continue
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

            for lane_id in self.incoming_lanes.get(tl_id, []):
                q, t_wait, avg_wait, p_score, emg_cnt, emg_stop = self._lane_wait_features(lane_id)
                total_queue += q
                total_wait += t_wait
                total_priority += p_score
                total_emergency += emg_cnt
                total_emergency_stopped += emg_stop
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
                min(total_priority / 120.0, 1.0),
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

        for veh_id in traci.vehicle.getIDList():
            veh_type = traci.vehicle.getTypeID(veh_id)
            wait_t = traci.vehicle.getWaitingTime(veh_id)
            is_stopped = traci.vehicle.getSpeed(veh_id) < 0.1
            if veh_type in self.EMERGENCY_TYPES:
                waiting_emergency += wait_t
                stopped_emergency += 1.0 if is_stopped else 0.0
            else:
                waiting_normal += wait_t
                stopped_normal += 1.0 if is_stopped else 0.0

        ped_wait = 0.0
        ped_stopped = 0.0
        for person_id in traci.person.getIDList():
            try:
                wt = traci.person.getWaitingTime(person_id)
                ped_wait += wt
                if traci.person.getSpeed(person_id) < 0.05:
                    ped_stopped += 1.0
            except Exception:
                continue

        # Arrivals is the right throughput signal for "vehicles left the network".
        departed = float(traci.simulation.getArrivedNumber())

        return {
            "waiting_normal": waiting_normal,
            "waiting_emergency": waiting_emergency,
            "stopped_normal": stopped_normal,
            "stopped_emergency": stopped_emergency,
            "ped_wait": ped_wait,
            "ped_stopped": ped_stopped,
            "arrived": departed,
        }

    def get_reward(self, step_meta: Dict[str, Dict[str, float]]) -> Tuple[float, Dict[str, float]]:
        """Global reward with stronger emergency/pedestrian penalties."""
        snap = self._reward_snapshot()
        prev = self.prev_reward_snapshot or snap

        delta_wait_normal = snap["waiting_normal"] - prev["waiting_normal"]
        delta_wait_emergency = snap["waiting_emergency"] - prev["waiting_emergency"]
        delta_wait_ped = snap["ped_wait"] - prev["ped_wait"]

        delta_stop_normal = snap["stopped_normal"] - prev["stopped_normal"]
        delta_stop_emergency = snap["stopped_emergency"] - prev["stopped_emergency"]
        delta_stop_ped = snap["ped_stopped"] - prev["ped_stopped"]

        throughput = max(0.0, snap["arrived"] - prev["arrived"])

        # Penalty: pedestrian green with no pedestrians waiting.
        empty_ped_green_penalty = 0.0
        for tl_id, meta in step_meta.items():
            if meta.get("is_ped_green", 0.0) > 0.5 and meta.get("ped_wait", 0.0) <= 0.01:
                empty_ped_green_penalty += 1.0

        # Positive reward if remaining stopped vehicles is reduced after action.
        previous_total_stopped = prev["stopped_normal"] + prev["stopped_emergency"]
        current_total_stopped = snap["stopped_normal"] + snap["stopped_emergency"]
        reduced_stop_bonus = 1.0 if current_total_stopped < previous_total_stopped else 0.0

        no_emergency_stop_bonus = 1.0 if snap["stopped_emergency"] <= 0 else 0.0

        reward_components = {
            "wait_normal_penalty": -0.01 * delta_wait_normal,
            "wait_emergency_penalty": -0.05 * delta_wait_emergency,
            "wait_ped_penalty": -0.03 * delta_wait_ped,
            "stop_normal_penalty": -0.30 * delta_stop_normal,
            "stop_emergency_penalty": -1.00 * delta_stop_emergency,
            "stop_ped_penalty": -0.60 * delta_stop_ped,
            "throughput_bonus": 0.80 * throughput,
            "no_emergency_stop_bonus": 0.60 * no_emergency_stop_bonus,
            "priority_flow_bonus": 0.50 * reduced_stop_bonus,
            "empty_ped_green_penalty": -0.60 * empty_ped_green_penalty,
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

    def step(self, actions: Dict[str, int]) -> Tuple[Dict[str, np.ndarray], float, bool, Dict[str, Any]]:
        """Apply joint action, advance simulation, and return next state and global reward."""
        step_meta: Dict[str, Dict[str, float]] = {}

        for tl_id, action in actions.items():
            spec = self.tl_specs[tl_id]
            transition = TrafficActions.execute_action(tl_id, int(action), spec)
            new_phase = int(transition["new_phase"])
            current_phase = int(traci.trafficlight.getPhase(tl_id))

            step_meta[tl_id] = {
                "action": float(action),
                "phase": float(current_phase),
                "new_phase": float(new_phase),
                "is_yellow": 1.0 if current_phase in spec.yellow_phases else 0.0,
                "is_ped_green": 1.0 if current_phase in spec.pedestrian_green_phases else 0.0,
                "ped_wait": self._pedestrian_wait_pressure(tl_id),
                "switched": float(transition["switched"]),
            }

        injection_stats = self._inject_live_records()

        traci.simulationStep()
        self.episode_step += 1

        snapshot_now = self._reward_snapshot()
        snapshot_prev = self.prev_reward_snapshot or snapshot_now
        arrived_delta = max(0.0, snapshot_now["arrived"] - snapshot_prev["arrived"])

        next_state = self.get_state()
        reward, reward_components = self.get_reward(step_meta)
        junction_diagnostics = self._collect_junction_diagnostics(step_meta, arrived_delta)
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
        }

        return next_state, reward, done, info
