import json
import os
import sys
import time
import base64
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import traci

try:
    import pymongo
except Exception:
    pymongo = None

try:
    from bson import ObjectId
except Exception:
    ObjectId = None

# Add the project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, ".."))

from agents.multi_agent_system import MultiAgentSystem
from utils.sumo_env_new import SumoEnv
from system_analytics import SystemAnalyticsStore

try:
    from dashboard_server import SimpleDashboardServer

    DASHBOARD_AVAILABLE = True
except Exception:
    DASHBOARD_AVAILABLE = False


class MARLExecutor:
    """Persistent multi-mode execution (MARL/fixed/manual) with per-junction switching."""

    def __init__(self, config_path: str = None):
        self.root = os.path.join(PROJECT_ROOT, "..")
        self.config_path = config_path or os.path.join(self.root, "configs", "marl_config.json")

        self.config = self._load_config(self.config_path)
        self._prepare_paths()

        print(f"Using config: {self.config_path}")
        print(f"SUMO config: {self.config['sumo_config_path']}")

        self.env = SumoEnv(
            config_path=self.config["sumo_config_path"],
            use_gui=bool(self.config.get("use_gui", True)),
            env_config=dict(self.config.get("env_config", {})),
        )
        self.env.start()

        self.agent_ids = self.env.tl_ids
        print(f"Agents: {self.agent_ids}")

        init_state = self.env.get_state()
        sample_id = self.agent_ids[0]
        base_state_dim = int(init_state[sample_id].shape[0])

        agent_cfg = dict(self.config.get("agent_config", {}))
        agent_cfg["enable_communication"] = True

        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            base_state_dim=base_state_dim,
            action_dim=agent_cfg.get("num_actions", 5),
            config=agent_cfg,
        )

        print(f"State dims: base={base_state_dim}, enhanced={self.multi_agent.state_dim}")

        loaded_path = self._load_models()
        if loaded_path:
            print(f"Loaded trained models from: {loaded_path}")
        else:
            print("WARNING: No models loaded, policy may act randomly")

        for agent in self.multi_agent.agents.values():
            agent.epsilon = 0.0

        self.metrics = {
            "start_time": datetime.now().isoformat(),
            "total_steps": 0,
            "total_reward": 0.0,
            "reward_history": [],
            "vehicle_count_history": [],
            "avg_speed_history": [],
            "action_history": [],
            "injection_history": [],
            "mode_history": [],
            "mode_switch_events": [],
        }

        self._init_mode_control()
        self._init_live_frame_stream()
        self._init_dashboard()
        self._init_iot_signal_store()
        self._init_accident_store()
        self._init_system_analytics_store()

    def _load_config(self, path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config not found: {path}")

        with open(path, "r") as f:
            cfg = json.load(f)

        sumo_cfg = cfg.get("sumo_config_path", "sumo_configs/3junctions.sumocfg")
        if not os.path.isabs(sumo_cfg):
            cfg["sumo_config_path"] = os.path.join(self.root, sumo_cfg)

        if not os.path.exists(cfg["sumo_config_path"]):
            raise FileNotFoundError(f"SUMO config not found: {cfg['sumo_config_path']}")

        cfg.setdefault("agent_config", {})
        cfg.setdefault("env_config", {})
        cfg.setdefault("max_steps_per_episode", 3600)
        cfg.setdefault("control_modes", {})

        control_cfg = cfg["control_modes"]
        control_cfg.setdefault("default_mode", "marl")
        control_cfg.setdefault("fixed_green_steps", 40)
        control_cfg.setdefault("fixed_pedestrian_steps", 15)
        control_cfg.setdefault("dashboard_enabled", True)
        control_cfg.setdefault("dashboard_host", "localhost")
        control_cfg.setdefault("dashboard_port", 8765)
        control_cfg.setdefault("stream_sumo_gui", True)
        control_cfg.setdefault("stream_frame_interval_steps", 20)
        control_cfg.setdefault("stream_frame_width", 960)
        control_cfg.setdefault("stream_frame_height", 540)

        # Execution should run continuously until user stops it.
        execution_max_steps = int(cfg.get("execution_max_steps", 0))
        if execution_max_steps <= 0:
            execution_max_steps = 10**9
        cfg["env_config"]["max_steps_per_episode"] = execution_max_steps

        # For execution we usually want external live inserts only.
        cfg["env_config"]["enable_data_injection"] = True

        return cfg

    def _prepare_paths(self) -> None:
        self.logs_dir = os.path.join(self.root, "logs", "execution")
        os.makedirs(self.logs_dir, exist_ok=True)

    def _init_live_frame_stream(self) -> None:
        control_cfg = self.config.get("control_modes", {})
        self.live_frame_enabled = bool(control_cfg.get("stream_sumo_gui", True)) and bool(self.config.get("use_gui", True))
        self.live_frame_interval_steps = max(5, int(control_cfg.get("stream_frame_interval_steps", 20)))
        self.live_frame_width = max(320, int(control_cfg.get("stream_frame_width", 960)))
        self.live_frame_height = max(240, int(control_cfg.get("stream_frame_height", 540)))

        self._live_frame_last_step = -10**9
        self._live_frame_failures = 0
        self._sumo_view_id = ""
        self.stream_frames_to_dashboard = False

        self.live_frames_dir = os.path.join(self.logs_dir, "live_frames")
        os.makedirs(self.live_frames_dir, exist_ok=True)
        self.live_frame_path = os.path.join(self.live_frames_dir, "latest_frame.png")

    def _resolve_sumo_view_id(self) -> str:
        if self._sumo_view_id:
            return self._sumo_view_id
        try:
            views = list(traci.gui.getIDList())
            if views:
                self._sumo_view_id = str(views[0])
        except Exception:
            self._sumo_view_id = ""
        return self._sumo_view_id

    def _capture_live_frame(self, step: int) -> str:
        """Capture one SUMO GUI frame and return it as a PNG data URL."""
        if not self.live_frame_enabled:
            return ""
        if step - self._live_frame_last_step < self.live_frame_interval_steps:
            return ""

        view_id = self._resolve_sumo_view_id()
        if not view_id:
            return ""

        try:
            traci.gui.screenshot(
                view_id,
                self.live_frame_path,
                self.live_frame_width,
                self.live_frame_height,
            )
            with open(self.live_frame_path, "rb") as f:
                payload = base64.b64encode(f.read()).decode("ascii")

            self._live_frame_last_step = step
            self._live_frame_failures = 0
            return f"data:image/png;base64,{payload}"
        except Exception:
            self._live_frame_failures += 1
            if self._live_frame_failures > 5:
                self.live_frame_enabled = False
            return ""

    def _init_mode_control(self) -> None:
        valid_modes = {"marl", "fixed", "manual"}
        requested_default = str(self.config.get("control_modes", {}).get("default_mode", "marl")).lower()
        default_mode = requested_default if requested_default in valid_modes else "marl"
        fixed_green_steps = int(self.config.get("control_modes", {}).get("fixed_green_steps", 40))
        fixed_green_steps = fixed_green_steps if fixed_green_steps in {20, 40, 60} else 40
        fixed_pedestrian_steps = int(self.config.get("control_modes", {}).get("fixed_pedestrian_steps", 15))
        fixed_pedestrian_steps = max(5, fixed_pedestrian_steps)

        self.default_mode = default_mode
        self.junction_modes: Dict[str, str] = {tl_id: default_mode for tl_id in self.agent_ids}
        self.fixed_state: Dict[str, Dict[str, int]] = {
            tl_id: {
                "action": 0,
                "elapsed": 0,
                "green_steps": fixed_green_steps,
                "vehicle_green_steps": fixed_green_steps,
                "pedestrian_green_steps": fixed_pedestrian_steps,
            }
            for tl_id in self.agent_ids
        }
        self.manual_state: Dict[str, int] = {tl_id: 4 for tl_id in self.agent_ids}

    def _init_system_analytics_store(self) -> None:
        env_cfg = dict(self.config.get("env_config", {}))
        self.analytics_store = SystemAnalyticsStore(
            env_config=env_cfg,
            sumo_cfg=str(self.config.get("sumo_config_path", "")),
        )

    def _is_pedestrian_action(self, junction_id: str, action: int) -> bool:
        spec = self.env.tl_specs.get(junction_id)
        if spec is None:
            return False
        green_phase = spec.action_to_green.get(int(action))
        return green_phase in spec.pedestrian_green_phases

    def _fixed_steps_for_action(self, junction_id: str, action: int) -> int:
        state = self.fixed_state.get(junction_id, {})
        if self._is_pedestrian_action(junction_id, action):
            return int(state.get("pedestrian_green_steps", 15))
        return int(state.get("vehicle_green_steps", state.get("green_steps", 40)))

    def _init_dashboard(self) -> None:
        self.dashboard = None
        if not DASHBOARD_AVAILABLE:
            print("Dashboard server not available; running without remote control API")
            return

        control_cfg = self.config.get("control_modes", {})
        if not bool(control_cfg.get("dashboard_enabled", True)):
            print("Dashboard control disabled by config")
            return

        host = str(control_cfg.get("dashboard_host", "localhost"))
        port = int(control_cfg.get("dashboard_port", 8765))
        try:
            self.dashboard = SimpleDashboardServer(host=host, port=port)
            self.dashboard.start()
            print(f"Dashboard command server: ws://{host}:{port}")
            self._broadcast_runtime_state(reason="startup")
        except Exception as exc:
            print(f"Failed to start dashboard server: {exc}")
            self.dashboard = None

    def _init_iot_signal_store(self) -> None:
        """Initialize MongoDB store used for Arduino traffic-light state sync."""
        self.iot_client = None
        self.iot_collection = None

        if pymongo is None:
            print("IOT signal publishing disabled: pymongo is not installed")
            return

        env_cfg = self.config.get("env_config", {})
        self.iot_mongo_uri = str(
            env_cfg.get(
                "mongo_uri",
                "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
            )
        )
        self.iot_db_name = str(env_cfg.get("iot_mongo_db", "EmergencyDetection"))
        self.iot_collection_name = str(env_cfg.get("iot_signals_collection", "Traffic_Signals_IOT"))

        try:
            self.iot_client = pymongo.MongoClient(self.iot_mongo_uri)
            self.iot_client.admin.command("ping")
            self.iot_collection = self.iot_client[self.iot_db_name][self.iot_collection_name]
            self._ensure_iot_seed_records()
            print(
                f"IOT signal publishing enabled: {self.iot_db_name}.{self.iot_collection_name}"
            )
        except Exception as exc:
            print(f"IOT signal publishing disabled (MongoDB error): {exc}")
            self.iot_client = None
            self.iot_collection = None

    def _init_accident_store(self) -> None:
        """Initialize MongoDB collection used for accident alert ingestion."""
        self.accident_client = None
        self.accident_collection = None

        if pymongo is None:
            print("Accident alert ingestion disabled: pymongo is not installed")
            return

        env_cfg = self.config.get("env_config", {})
        mongo_uri = str(
            env_cfg.get(
                "mongo_uri",
                "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
            )
        )
        db_name = str(env_cfg.get("accident_mongo_db", env_cfg.get("iot_mongo_db", "EmergencyDetection")))
        collection_name = str(env_cfg.get("accident_collection", "accident_detect"))

        try:
            # Reuse IOT Mongo client when it targets the same URI, to reduce connection churn.
            if self.iot_client is not None and mongo_uri == getattr(self, "iot_mongo_uri", ""):
                self.accident_client = self.iot_client
            else:
                self.accident_client = pymongo.MongoClient(mongo_uri)
                self.accident_client.admin.command("ping")
            self.accident_collection = self.accident_client[db_name][collection_name]
            print(f"Accident alert ingestion enabled: {db_name}.{collection_name}")
        except Exception as exc:
            print(f"Accident alert ingestion disabled (MongoDB error): {exc}")
            self.accident_client = None
            self.accident_collection = None

    def _entrypoint_to_junction_lane(self, entry_point: str) -> Tuple[str, str]:
        mapping = {
            "-E0": ("J4", "west"),
            "E0": ("J4", "east"),
            "J4_c0": ("J4", "pedestrian"),
            "J4_c1": ("J4", "pedestrian"),
            "-E3": ("J1", "west"),
            "-E2": ("J1", "north"),
            "E00": ("J1", "east"),
            "-E5": ("J8", "north"),
            "-E4": ("J8", "east"),
            "-E8": ("J8", "south"),
            "E3": ("J8", "west"),
        }
        return mapping.get(str(entry_point), ("", ""))

    def _junction_display_name(self, junction_id: str) -> str:
        names = {
            "J1": "Weliwita Junction",
            "J4": "SLIIT Junction",
            "J8": "Kaduwela Junction",
        }
        return names.get(str(junction_id), str(junction_id))

    def _lane_display_name(self, lane_id: str) -> str:
        names = {
            "west": "West lane",
            "east": "East lane",
            "north": "North lane",
            "south": "South lane",
            "pedestrian": "Pedestrian crossing",
        }
        return names.get(str(lane_id), str(lane_id))

    def _serialize_accident_doc(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(doc.get("data", {}) or {})
        entry_point = str(payload.get("entryPoint", "") or "")
        road_id = str(payload.get("roadId", "") or "").lower()
        junction_id, lane_id = self._entrypoint_to_junction_lane(entry_point)

        if not lane_id and road_id in {"west", "east", "north", "south", "pedestrian"}:
            lane_id = road_id

        return {
            "id": str(doc.get("_id", "")),
            "timestamp": str(doc.get("timestamp", "")),
            "type": str(doc.get("type", "accident")),
            "status": str(payload.get("status", "")),
            "entryPoint": entry_point,
            "roadId": road_id,
            "camera": str(payload.get("camera", "")),
            "label": str(payload.get("label", "Accident")),
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "detectedArea": str(payload.get("detectedArea", "")),
            "manualCommand": str(payload.get("manualCommand", "")),
            "junction_id": junction_id,
            "junction_name": self._junction_display_name(junction_id) if junction_id else "Unknown Junction",
            "lane_id": lane_id,
            "lane_name": self._lane_display_name(lane_id) if lane_id else "Unknown lane",
        }

    def _read_active_accidents(self) -> Dict[str, Any]:
        """Read active accidents and aggregate by junction and entry edge for dashboard use."""
        base = {
            "count": 0,
            "active": [],
            "by_junction": {},
            "by_edge": {},
            "updated_at": self._iso_utc_now(),
        }

        if self.accident_collection is None:
            return base

        try:
            cursor = self.accident_collection.find({
                "type": {"$in": ["accident", "Accident"]},
                "data.status": {"$in": ["ACTIVE", "active"]},
            }).sort("timestamp", pymongo.DESCENDING).limit(50)

            active: List[Dict[str, Any]] = []
            by_junction: Dict[str, int] = {}
            by_edge: Dict[str, Dict[str, int]] = {}

            for doc in cursor:
                event = self._serialize_accident_doc(dict(doc))
                active.append(event)

                junction_id = str(event.get("junction_id", "") or "")
                entry_point = str(event.get("entryPoint", "") or "")
                if junction_id:
                    by_junction[junction_id] = int(by_junction.get(junction_id, 0)) + 1
                    if entry_point:
                        by_edge.setdefault(junction_id, {})
                        by_edge[junction_id][entry_point] = int(by_edge[junction_id].get(entry_point, 0)) + 1

            base["count"] = len(active)
            base["active"] = active
            base["by_junction"] = by_junction
            base["by_edge"] = by_edge
            return base
        except Exception:
            return base

    def _resolve_accident(self, accident_id: str) -> None:
        if self.accident_collection is None:
            return
        doc_id: Any = str(accident_id or "").strip()
        if not doc_id:
            return

        filters: List[Dict[str, Any]] = [{"_id": doc_id}]
        if ObjectId is not None:
            try:
                filters.append({"_id": ObjectId(doc_id)})
            except Exception:
                pass

        for query in filters:
            try:
                result = self.accident_collection.update_one(
                    query,
                    {
                        "$set": {
                            "data.status": "CONTROLLED",
                            "data.resolvedAt": self._iso_utc_now(),
                        }
                    },
                )
                if int(getattr(result, "matched_count", 0)) > 0:
                    break
            except Exception:
                continue

    def _iso_utc_now(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _junction_signal_payload(self, junction_id: str, phase: int) -> Dict[str, str]:
        """Map SUMO live signal state to per-road red/yellow/green values for IOT consumers."""

        # Link-index groups from 3junctions.net.xml for controlled approaches/crossings.
        link_groups: Dict[str, Dict[str, List[int]]] = {
            "J1": {
                "-E3": [0, 1, 2],
                "E00": [3, 4, 5],
                "-E2": [6, 7, 8],
            },
            "J4": {
                "-E0": [0, 1, 2],
                "E0": [3, 4, 5],
                "J4_c0": [6],
                "J4_c1": [7],
            },
            "J8": {
                "-E4": [0, 1, 2, 3],
                "-E5": [4, 5, 6, 7],
                "-E8": [8, 9, 10, 11],
                "E3": [12, 13, 14, 15],
            },
        }

        groups = link_groups.get(junction_id)
        if not groups:
            return {}

        payload = {edge_id: "red" for edge_id in groups.keys()}

        def _char_to_color(signal_char: str) -> str:
            ch = str(signal_char)
            if ch in {"g", "G"}:
                return "green"
            if ch in {"y", "Y"}:
                return "yellow"
            return "red"

        def _merge_colors(colors: List[str]) -> str:
            if any(c == "green" for c in colors):
                return "green"
            if any(c == "yellow" for c in colors):
                return "yellow"
            return "red"

        try:
            live_state = str(traci.trafficlight.getRedYellowGreenState(junction_id))
            for edge_id, indices in groups.items():
                lane_colors = []
                for idx in indices:
                    if 0 <= int(idx) < len(live_state):
                        lane_colors.append(_char_to_color(live_state[int(idx)]))
                if lane_colors:
                    payload[edge_id] = _merge_colors(lane_colors)
            return payload
        except Exception:
            # Fallback to phase-based defaults when live state is unavailable.
            if junction_id == "J4":
                if int(phase) == 0:
                    payload["E0"] = "green"
                    payload["-E0"] = "green"
                elif int(phase) == 2:
                    payload["J4_c0"] = "green"
                    payload["J4_c1"] = "green"
            elif junction_id == "J1":
                lane = {0: "-E3", 2: "E00", 4: "-E2"}.get(int(phase))
                if lane:
                    payload[lane] = "green"
            elif junction_id == "J8":
                lane = {0: "-E4", 2: "-E5", 4: "-E8", 6: "E3"}.get(int(phase))
                if lane:
                    payload[lane] = "green"
            return payload

    def _upsert_junction_iot_record(self, junction_id: str, signal_state: Dict[str, str]) -> None:
        if self.iot_collection is None or not signal_state:
            return

        now_iso = self._iso_utc_now()
        doc = {
            "timestamp": now_iso,
            "junction": {
                junction_id: signal_state,
            },
        }

        self.iot_collection.update_one(
            {f"junction.{junction_id}": {"$exists": True}},
            {"$set": doc},
            upsert=True,
        )

    def _ensure_iot_seed_records(self) -> None:
        """Ensure one document exists per J1/J4/J8 in Traffic_Signals_IOT."""
        if self.iot_collection is None:
            return

        for junction_id in ["J4", "J1", "J8"]:
            try:
                phase = int(traci.trafficlight.getPhase(junction_id))
            except Exception:
                phase = -1
            signal_state = self._junction_signal_payload(junction_id, phase)
            self._upsert_junction_iot_record(junction_id, signal_state)

    def _publish_iot_signals(self, step_meta: Dict[str, Dict[str, float]]) -> None:
        """Update per-junction traffic-light state docs after each execution step."""
        if self.iot_collection is None:
            return

        for junction_id in ["J4", "J1", "J8"]:
            meta = step_meta.get(junction_id, {})
            if "phase" in meta:
                phase = int(meta.get("phase", -1))
            else:
                try:
                    phase = int(traci.trafficlight.getPhase(junction_id))
                except Exception:
                    phase = -1

            signal_state = self._junction_signal_payload(junction_id, phase)
            self._upsert_junction_iot_record(junction_id, signal_state)

    def _record_mode_event(self, event_type: str, payload: Dict[str, object]) -> None:
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        self.metrics["mode_switch_events"].append(event)

    def _runtime_mode_summary(self) -> Dict[str, object]:
        active = set(self.junction_modes.values())
        global_mode = list(active)[0] if len(active) == 1 else "mixed"
        return {
            "global_mode": global_mode,
            "junction_modes": dict(self.junction_modes),
            "manual_actions": dict(self.manual_state),
            "fixed_state": {k: dict(v) for k, v in self.fixed_state.items()},
        }

    def _broadcast_runtime_state(self, reason: str = "update") -> None:
        if self.dashboard is None:
            return
        payload = self._runtime_mode_summary()
        payload["reason"] = reason
        self.dashboard.send_mode_update(payload)

    def _set_global_mode(self, mode: str) -> None:
        mode = str(mode).lower()
        if mode not in {"marl", "fixed", "manual"}:
            return
        for tl_id in self.agent_ids:
            self.junction_modes[tl_id] = mode
        self._record_mode_event("set_global_mode", {"mode": mode})

    def _set_junction_mode(self, junction_id: str, mode: str) -> None:
        if junction_id not in self.junction_modes:
            return
        mode = str(mode).lower()
        if mode not in {"marl", "fixed", "manual"}:
            return
        self.junction_modes[junction_id] = mode
        self._record_mode_event("set_junction_mode", {"junction_id": junction_id, "mode": mode})

    def _set_manual_action(self, junction_id: str, action: int) -> None:
        if junction_id not in self.manual_state:
            return
        action = int(action)
        if action < 0 or action > 4:
            return
        self.manual_state[junction_id] = action
        self._record_mode_event("set_manual_action", {"junction_id": junction_id, "action": action})

    def _set_fixed_timing(self, junction_id: str, green_steps: int) -> None:
        green_steps = int(green_steps)
        if green_steps not in {20, 40, 60}:
            return
        if junction_id == "*":
            for tl_id in self.agent_ids:
                self.fixed_state[tl_id]["green_steps"] = green_steps
                self.fixed_state[tl_id]["vehicle_green_steps"] = green_steps
                self.fixed_state[tl_id]["pedestrian_green_steps"] = 15
            self._record_mode_event("set_fixed_timing", {"junction_id": "*", "green_steps": green_steps})
            return

        if junction_id in self.fixed_state:
            self.fixed_state[junction_id]["green_steps"] = green_steps
            self.fixed_state[junction_id]["vehicle_green_steps"] = green_steps
            self.fixed_state[junction_id]["pedestrian_green_steps"] = 15
            self._record_mode_event("set_fixed_timing", {"junction_id": junction_id, "green_steps": green_steps})

    def _process_dashboard_commands(self) -> None:
        if self.dashboard is None:
            return

        changed = False
        commands = self.dashboard.get_pending_commands(max_items=200)
        for cmd in commands:
            ctype = str(cmd.get("type", "")).lower()
            if ctype == "set_global_mode":
                self._set_global_mode(str(cmd.get("mode", "marl")))
                changed = True
            elif ctype == "set_junction_mode":
                self._set_junction_mode(str(cmd.get("junction_id", "")), str(cmd.get("mode", "marl")))
                changed = True
            elif ctype == "set_manual_action":
                self._set_manual_action(str(cmd.get("junction_id", "")), int(cmd.get("action", 4)))
                changed = True
            elif ctype == "set_fixed_timing":
                self._set_fixed_timing(str(cmd.get("junction_id", "*")), int(cmd.get("green_steps", 40)))
                changed = True
            elif ctype == "resolve_accident":
                payload = cmd.get("payload", {}) if isinstance(cmd.get("payload"), dict) else {}
                accident_id = str(payload.get("accident_id", "") or cmd.get("accident_id", ""))
                self._resolve_accident(accident_id)
                changed = True
            elif ctype == "set_frame_streaming":
                payload = cmd.get("payload", {}) if isinstance(cmd.get("payload"), dict) else {}
                enabled = bool(payload.get("enabled", cmd.get("enabled", False)))
                self.stream_frames_to_dashboard = enabled
            elif ctype == "get_runtime_state":
                changed = True
            elif ctype == "get_analytics_summary":
                payload = cmd.get("payload", {}) if isinstance(cmd.get("payload"), dict) else {}
                range_key = str(payload.get("range", "6h"))
                mode_variant = str(payload.get("mode_variant", "all"))
                if self.dashboard is not None and self.analytics_store is not None:
                    result = self.analytics_store.query_summary(range_key=range_key, mode_variant=mode_variant)
                    self.dashboard.send_analytics_update(result)

        if changed:
            self._broadcast_runtime_state(reason="command")

    def _next_fixed_action(self, junction_id: str) -> int:
        state = self.fixed_state[junction_id]
        tl_spec = self.env.tl_specs.get(junction_id)
        action_count = max(1, len(tl_spec.action_to_green)) if tl_spec is not None else 4
        current_action = int(state["action"])
        current_steps = self._fixed_steps_for_action(junction_id, current_action)
        state["green_steps"] = current_steps

        if state["elapsed"] >= current_steps:
            state["action"] = (state["action"] + 1) % action_count
            state["elapsed"] = 0
        action = int(state["action"])
        state["green_steps"] = self._fixed_steps_for_action(junction_id, action)
        state["elapsed"] += 1
        return action

    def _select_joint_actions(self, state: Dict[str, np.ndarray]) -> Dict[str, int]:
        marl_actions = self.multi_agent.act_with_coordination(state, training_mode=False)
        final_actions: Dict[str, int] = {}

        for tl_id in self.agent_ids:
            mode = self.junction_modes.get(tl_id, "marl")
            if mode == "marl":
                action = int(marl_actions.get(tl_id, 4))
            elif mode == "fixed":
                action = self._next_fixed_action(tl_id)
            else:
                action = int(self.manual_state.get(tl_id, 4))
            final_actions[tl_id] = action

        return final_actions

    def _build_junction_live_metrics(
        self,
        state: Dict[str, np.ndarray],
        info: Dict[str, object],
        accidents_by_edge: Optional[Dict[str, Dict[str, int]]] = None,
        accidents_by_junction: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Dict[str, float]]:
        """Build compact per-junction metrics for dashboard and detailed junction page."""
        out: Dict[str, Dict[str, float]] = {}
        diagnostics = dict(info.get("junction_diagnostics", {}))
        step_meta = dict(info.get("step_meta", {}))

        for tl_id in self.agent_ids:
            live_metrics = dict(info.get("junction_live_metrics", {}).get(tl_id, {}))
            if live_metrics:
                phase = -1
                try:
                    phase = int(dict(step_meta.get(tl_id, {})).get("phase", -1))
                except Exception:
                    phase = -1
                if phase < 0:
                    try:
                        phase = int(traci.trafficlight.getPhase(tl_id))
                    except Exception:
                        phase = -1

                signal_state = self._junction_signal_payload(tl_id, phase)
                edge_accidents = dict((accidents_by_edge or {}).get(tl_id, {}))
                junction_accidents = int((accidents_by_junction or {}).get(tl_id, 0))

                out[tl_id] = {
                    "vehicles_waiting": float(live_metrics.get("vehicles_waiting", 0.0)),
                    "vehicle_density": float(live_metrics.get("vehicle_density", 0.0)),
                    "avg_wait_time": float(live_metrics.get("avg_wait_time", 0.0)),
                    "pedestrians": int(live_metrics.get("pedestrians", 0)),
                    "pedestrians_waiting": int(live_metrics.get("pedestrians_waiting", 0)),
                    "pedestrian_wait_total": float(live_metrics.get("pedestrian_wait_total", 0.0)),
                    "pedestrian_avg_wait_time": float(live_metrics.get("pedestrian_avg_wait_time", 0.0)),
                    "pedestrian_types": dict(live_metrics.get("pedestrian_types", {})),
                    "emergency": int(live_metrics.get("emergency", 0)),
                    "lane_counts": list(live_metrics.get("lane_counts", [])),
                    "lane_counts_by_edge": dict(live_metrics.get("lane_counts_by_edge", {})),
                    "signal_state": signal_state,
                    "accidents": junction_accidents,
                    "accidents_by_edge": edge_accidents,
                    "lane_metrics": dict(live_metrics.get("lane_metrics", {})),
                }
                continue

            vec = np.asarray(state.get(tl_id, np.zeros(9, dtype=np.float32)), dtype=np.float32)
            diag = dict(diagnostics.get(tl_id, {}))

            total_queue = float(np.clip(vec[-9] * 100.0, 0.0, 9999.0)) if vec.size >= 9 else 0.0
            avg_wait = float(np.clip(vec[-7] * 90.0, 0.0, 9999.0)) if vec.size >= 7 else 0.0

            emergency_by_lane = dict(diag.get("emergency_detected_by_lane", {}))
            normal_by_lane = dict(diag.get("normal_detected_by_lane", {}))

            combined_by_lane: Dict[str, int] = {}
            for lane_id in set(list(normal_by_lane.keys()) + list(emergency_by_lane.keys())):
                combined_by_lane[lane_id] = int(normal_by_lane.get(lane_id, 0)) + int(
                    emergency_by_lane.get(lane_id, 0)
                )

            counts_by_edge: Dict[str, int] = {}
            for lane_id, lane_count in combined_by_lane.items():
                edge_id = lane_id.split("_")[0] if "_" in lane_id else lane_id
                counts_by_edge[edge_id] = int(counts_by_edge.get(edge_id, 0)) + int(lane_count)

            lane_counts = []
            for lane_id in sorted(combined_by_lane.keys()):
                lane_counts.append(int(combined_by_lane.get(lane_id, 0)))
            lane_counts.sort(reverse=True)

            emergency_count = int(sum(int(v) for v in emergency_by_lane.values()))
            pedestrians = int(diag.get("pedestrians_detected", 0))

            phase = -1
            try:
                phase = int(dict(step_meta.get(tl_id, {})).get("phase", -1))
            except Exception:
                phase = -1
            if phase < 0:
                try:
                    phase = int(traci.trafficlight.getPhase(tl_id))
                except Exception:
                    phase = -1

            signal_state = self._junction_signal_payload(tl_id, phase)
            edge_accidents = dict((accidents_by_edge or {}).get(tl_id, {}))
            junction_accidents = int((accidents_by_junction or {}).get(tl_id, 0))

            out[tl_id] = {
                "vehicles_waiting": total_queue,
                "vehicle_density": float(min(1.0, total_queue / 100.0)),
                "avg_wait_time": avg_wait,
                "pedestrians": pedestrians,
                "emergency": emergency_count,
                "lane_counts": lane_counts,
                "lane_counts_by_edge": counts_by_edge,
                "signal_state": signal_state,
                "accidents": junction_accidents,
                "accidents_by_edge": edge_accidents,
            }

        return out

    def _load_models(self) -> str:
        model_dirs = [
            os.path.join(self.root, "models", "episode_20"),
        ]

        for mdir in model_dirs:
            if os.path.exists(mdir) and self.multi_agent.load_models(mdir):
                return mdir
        return ""

    def run(self) -> None:
        print("=" * 60)
        print("DECENTRALIZED EXECUTION STARTED")
        print("Press Ctrl+C to stop")
        print("=" * 60)

        state = self.env.reset()
        step = 0

        try:
            while True:
                self._process_dashboard_commands()
                actions = self._select_joint_actions(state)
                manual_overrides = {
                    tl_id: (self.junction_modes.get(tl_id) == "manual")
                    for tl_id in self.agent_ids
                }
                next_state, reward, done, info = self.env.step(
                    actions,
                    ignore_timing_for=manual_overrides,
                )
                self._publish_iot_signals(dict(info.get("step_meta", {})))

                self.metrics["total_steps"] += 1
                self.metrics["total_reward"] += float(reward)
                self.metrics["reward_history"].append(float(reward))
                self.metrics["vehicle_count_history"].append(int(info.get("vehicle_count", 0)))
                self.metrics["avg_speed_history"].append(float(info.get("avg_speed", 0.0)))
                self.metrics["action_history"].append({aid: int(a) for aid, a in actions.items()})
                self.metrics["injection_history"].append(info.get("injection_stats", {}))
                self.metrics["mode_history"].append(dict(self.junction_modes))

                if self.analytics_store is not None:
                    self.analytics_store.observe_step(
                        step_meta=dict(info.get("step_meta", {})),
                        actions={aid: int(a) for aid, a in actions.items()},
                        junction_modes=dict(self.junction_modes),
                        fixed_state={k: dict(v) for k, v in self.fixed_state.items()},
                        junction_live_metrics=dict(info.get("junction_live_metrics", {})),
                    )

                if step % 50 == 0:
                    print(
                        # f"Step {step} | reward={reward:.3f} | "
                        # f"vehicles={info.get('vehicle_count', 0)} | speed={info.get('avg_speed', 0.0):.2f}"
                    )
                    # print(f"  actions: {actions}")
                    # print(f"  modes: {self.junction_modes}")

                if self.dashboard is not None and step % 2 == 0:
                    frame_data = self._capture_live_frame(step) if self.stream_frames_to_dashboard else ""
                    accident_snapshot = self._read_active_accidents()
                    junction_live = self._build_junction_live_metrics(
                        next_state,
                        info,
                        accidents_by_edge=dict(accident_snapshot.get("by_edge", {})),
                        accidents_by_junction=dict(accident_snapshot.get("by_junction", {})),
                    )
                    telemetry = {
                        "step": int(step),
                        "reward": float(reward),
                        "vehicle_count": int(info.get("vehicle_count", 0)),
                        "avg_speed": float(info.get("avg_speed", 0.0)),
                        "actions": {k: int(v) for k, v in actions.items()},
                        "modes": dict(self.junction_modes),
                        "injection_stats": dict(info.get("injection_stats", {})),
                        "step_meta": dict(info.get("step_meta", {})),
                        "junction_diagnostics": dict(info.get("junction_diagnostics", {})),
                        "junction_live": junction_live,
                        "accidents": accident_snapshot,
                    }
                    if frame_data:
                        telemetry["sumo_live_frame"] = frame_data
                    self.dashboard.send_traffic_update(telemetry)

                step += 1
                state = next_state

                # In execution mode, done can be ignored because max_steps is set very high.
                if done and step % 200 == 0:
                    print("Execution horizon flag raised; continuing without simulation reset.")

                time.sleep(0.05)

        except KeyboardInterrupt:
            print("\nExecution stopped by user")
        finally:
            self.save_logs()
            self.multi_agent.close()
            self.env.close()
            if self.iot_client is not None:
                self.iot_client.close()
            if self.accident_client is not None and self.accident_client is not self.iot_client:
                self.accident_client.close()
            if self.dashboard is not None:
                self.dashboard.send_system_status("stopped", "Execution stopped")
            if self.analytics_store is not None:
                self.analytics_store.flush()
                self.analytics_store.close()
            print("Execution cleanup complete")

    def save_logs(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        run_log = {
            "timestamp": datetime.now().isoformat(),
            "total_steps": int(self.metrics["total_steps"]),
            "total_reward": float(self.metrics["total_reward"]),
            "avg_reward": float(np.mean(self.metrics["reward_history"])) if self.metrics["reward_history"] else 0.0,
            "avg_vehicle_count": (
                float(np.mean(self.metrics["vehicle_count_history"])) if self.metrics["vehicle_count_history"] else 0.0
            ),
            "avg_speed": float(np.mean(self.metrics["avg_speed_history"])) if self.metrics["avg_speed_history"] else 0.0,
            "actions_last_200": self.metrics["action_history"][-200:],
            "injection_last_200": self.metrics["injection_history"][-200:],
            "modes_last_200": self.metrics["mode_history"][-200:],
            "mode_switch_events": self.metrics["mode_switch_events"],
            "config": self.config,
        }

        detail_path = os.path.join(self.logs_dir, f"execution_{timestamp}.json")
        with open(detail_path, "w") as f:
            json.dump(run_log, f, indent=2)

        summary_path = os.path.join(self.logs_dir, f"summary_{timestamp}.json")
        summary = {
            "timestamp": run_log["timestamp"],
            "total_steps": run_log["total_steps"],
            "total_reward": run_log["total_reward"],
            "avg_reward": run_log["avg_reward"],
            "avg_vehicle_count": run_log["avg_vehicle_count"],
            "avg_speed": run_log["avg_speed"],
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        print(f"Logs saved: {detail_path}")
        print(f"Summary saved: {summary_path}")


def main() -> None:
    executor = MARLExecutor()
    executor.run()


if __name__ == "__main__":
    main()
