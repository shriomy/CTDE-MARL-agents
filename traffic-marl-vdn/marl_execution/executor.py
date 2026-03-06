import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List

import numpy as np

# Add the project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, ".."))

from agents.multi_agent_system import MultiAgentSystem
from utils.sumo_env_new import SumoEnv

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
        self._init_dashboard()

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
        cfg.setdefault("max_steps_per_episode", 1800)
        cfg.setdefault("control_modes", {})

        control_cfg = cfg["control_modes"]
        control_cfg.setdefault("default_mode", "marl")
        control_cfg.setdefault("fixed_green_steps", 20)
        control_cfg.setdefault("dashboard_enabled", True)
        control_cfg.setdefault("dashboard_host", "localhost")
        control_cfg.setdefault("dashboard_port", 8765)

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

    def _init_mode_control(self) -> None:
        valid_modes = {"marl", "fixed", "manual"}
        requested_default = str(self.config.get("control_modes", {}).get("default_mode", "marl")).lower()
        default_mode = requested_default if requested_default in valid_modes else "marl"
        fixed_green_steps = int(self.config.get("control_modes", {}).get("fixed_green_steps", 20))
        fixed_green_steps = max(5, fixed_green_steps)

        self.default_mode = default_mode
        self.junction_modes: Dict[str, str] = {tl_id: default_mode for tl_id in self.agent_ids}
        self.fixed_state: Dict[str, Dict[str, int]] = {
            tl_id: {"action": 0, "elapsed": 0, "green_steps": fixed_green_steps} for tl_id in self.agent_ids
        }
        self.manual_state: Dict[str, int] = {tl_id: 4 for tl_id in self.agent_ids}

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
        green_steps = max(5, int(green_steps))
        if junction_id == "*":
            for tl_id in self.agent_ids:
                self.fixed_state[tl_id]["green_steps"] = green_steps
            self._record_mode_event("set_fixed_timing", {"junction_id": "*", "green_steps": green_steps})
            return

        if junction_id in self.fixed_state:
            self.fixed_state[junction_id]["green_steps"] = green_steps
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
                self._set_fixed_timing(str(cmd.get("junction_id", "*")), int(cmd.get("green_steps", 20)))
                changed = True
            elif ctype == "get_runtime_state":
                changed = True

        if changed:
            self._broadcast_runtime_state(reason="command")

    def _next_fixed_action(self, junction_id: str) -> int:
        state = self.fixed_state[junction_id]
        if state["elapsed"] >= state["green_steps"]:
            state["action"] = (state["action"] + 1) % 4
            state["elapsed"] = 0
        action = int(state["action"])
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

    def _load_models(self) -> str:
        model_dirs = [
            os.path.join(self.root, "models", "final"),
            os.path.join(self.root, "models", "episode_100"),
            os.path.join(self.root, "models", "episode_90"),
            os.path.join(self.root, "models", "episode_80"),
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
                next_state, reward, done, info = self.env.step(actions)

                self.metrics["total_steps"] += 1
                self.metrics["total_reward"] += float(reward)
                self.metrics["reward_history"].append(float(reward))
                self.metrics["vehicle_count_history"].append(int(info.get("vehicle_count", 0)))
                self.metrics["avg_speed_history"].append(float(info.get("avg_speed", 0.0)))
                self.metrics["action_history"].append({aid: int(a) for aid, a in actions.items()})
                self.metrics["injection_history"].append(info.get("injection_stats", {}))
                self.metrics["mode_history"].append(dict(self.junction_modes))

                if step % 50 == 0:
                    print(
                        f"Step {step} | reward={reward:.3f} | "
                        f"vehicles={info.get('vehicle_count', 0)} | speed={info.get('avg_speed', 0.0):.2f}"
                    )
                    print(f"  actions: {actions}")
                    print(f"  modes: {self.junction_modes}")

                if self.dashboard is not None and step % 2 == 0:
                    telemetry = {
                        "step": int(step),
                        "reward": float(reward),
                        "vehicle_count": int(info.get("vehicle_count", 0)),
                        "avg_speed": float(info.get("avg_speed", 0.0)),
                        "actions": {k: int(v) for k, v in actions.items()},
                        "modes": dict(self.junction_modes),
                        "injection_stats": dict(info.get("injection_stats", {})),
                    }
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
            if self.dashboard is not None:
                self.dashboard.send_system_status("stopped", "Execution stopped")
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
