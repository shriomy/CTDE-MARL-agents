import json
import os
import sys
import time
from datetime import datetime

import numpy as np

# Add the project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PROJECT_ROOT)
sys.path.append(os.path.join(PROJECT_ROOT, ".."))

from agents.multi_agent_system import MultiAgentSystem
from utils.sumo_env_new import SumoEnv


class MARLExecutor:
    """Decentralized execution of trained MARL agents with logging."""

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
        }

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
                actions = self.multi_agent.act_with_coordination(state, training_mode=False)
                next_state, reward, done, info = self.env.step(actions)

                self.metrics["total_steps"] += 1
                self.metrics["total_reward"] += float(reward)
                self.metrics["reward_history"].append(float(reward))
                self.metrics["vehicle_count_history"].append(int(info.get("vehicle_count", 0)))
                self.metrics["avg_speed_history"].append(float(info.get("avg_speed", 0.0)))
                self.metrics["action_history"].append({aid: int(a) for aid, a in actions.items()})
                self.metrics["injection_history"].append(info.get("injection_stats", {}))

                if step % 50 == 0:
                    print(
                        f"Step {step} | reward={reward:.3f} | "
                        f"vehicles={info.get('vehicle_count', 0)} | speed={info.get('avg_speed', 0.0):.2f}"
                    )
                    print(f"  actions: {actions}")

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
