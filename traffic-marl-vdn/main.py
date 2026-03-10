import json
import os
import time
from collections import defaultdict
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np

from agents.multi_agent_system import MultiAgentSystem
from utils.sumo_env_new import SumoEnv


class Trainer:
    """Main centralized training entrypoint for MARL traffic control."""

    def __init__(self, config_path: str = "configs/marl_config.json"):
        self.config = self.load_config(config_path)
        self.setup_directories()

        print("Initializing SUMO environment...")
        env_config = dict(self.config.get("env_config", {}))
        env_config["max_steps_per_episode"] = self.config.get("max_steps_per_episode", 1800)

        self.env = SumoEnv(
            config_path=self.config["sumo_config_path"],
            use_gui=self.config.get("use_gui", False),
            env_config=env_config,
        )
        self.env.start()

        self.agent_ids = self.env.tl_ids
        print(f"Agents: {self.agent_ids}")

        initial_state = self.env.get_state()
        sample_agent = self.agent_ids[0]
        base_state_dim = int(initial_state[sample_agent].shape[0])

        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            base_state_dim=base_state_dim,
            action_dim=self.config["agent_config"].get("num_actions", 5),
            config=self.config["agent_config"],
        )

        print(f"DEBUG: Base state dim: {base_state_dim}")
        print(f"DEBUG: Enhanced state dim: {self.multi_agent.state_dim}")

        self.episode_rewards = []
        self.episode_lengths = []
        self.losses = []

    def load_config(self, config_path: str) -> dict:
        default_config = {
            "sumo_config_path": "sumo_configs/3junctions.sumocfg",
            "use_gui": False,
            "num_episodes": 50,
            "max_steps_per_episode": 1800,
            "save_frequency": 10,
            "log_frequency": 1,
            "agent_config": {
                "learning_rate": 1e-4,
                "gamma": 0.99,
                "epsilon_start": 1.0,
                "epsilon_min": 0.05,
                "epsilon_decay": 0.9995,
                "buffer_size": 10000,
                "central_buffer_size": 50000,
                "batch_size": 32,
                "target_update_freq": 50,
                "enable_communication": True,
                "neighbor_feature_dim": 8,
                "grad_clip": 1.0,
                "num_actions": 5,
            },
            "env_config": {
                "enable_data_injection": True,
                "injection_poll_interval": 1.0,
                "min_green_time": 20,
                "max_green_time": 90,
                "yellow_time": 3,
                "green_extension": 5,
                "min_ped_green_time": 12,
                "max_ped_green_time": 45,
            },
        }

        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                if isinstance(value, dict) and isinstance(default_config.get(key), dict):
                    default_config[key].update(value)
                else:
                    default_config[key] = value

        return default_config

    def setup_directories(self) -> None:
        os.makedirs("models", exist_ok=True)
        os.makedirs("logs", exist_ok=True)
        os.makedirs("logs/training", exist_ok=True)
        os.makedirs("configs", exist_ok=True)

        config_path = f"configs/config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(config_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def train_episode(self, episode: int):
        state = self.env.reset()
        total_reward = 0.0
        episode_loss = 0.0
        step_count = 0

        reward_breakdown_sum = {}
        total_injected = {"emergency": 0, "normal": 0, "pedestrian": 0}
        junction_metrics = {
            tl_id: {
                "emergency_detected_by_lane": defaultdict(int),
                "normal_detected_by_lane": defaultdict(int),
                "pedestrians_detected_total": 0,
                "pedestrians_detected_max": 0,
                "green_change_checks": 0,
                "green_change_drops": 0,
                "green_change_left_vehicle_drop_rate": 0.0,
                "emergency_stops": 0,
                "emergency_passed_without_stop": 0,
                "most_priority_lane_histogram": defaultdict(int),
                "ped_green_when_empty": 0,
            }
            for tl_id in self.agent_ids
        }

        for step in range(self.config["max_steps_per_episode"]):
            actions = self.multi_agent.act_with_coordination(state, training_mode=True)
            next_state, reward, done, info = self.env.step(actions)

            enhanced_states = [self.multi_agent.last_enhanced_states[aid] for aid in self.agent_ids]
            enhanced_next = self.multi_agent.build_next_enhanced_states(next_state)
            enhanced_next_states = [enhanced_next[aid] for aid in self.agent_ids]

            state_array = np.array(enhanced_states, dtype=np.float32)
            action_array = np.array([actions[aid] for aid in self.agent_ids], dtype=np.int64)
            next_state_array = np.array(enhanced_next_states, dtype=np.float32)

            experience = (state_array, action_array, float(reward), next_state_array, bool(done))
            self.multi_agent.remember(experience)

            loss, _ = self.multi_agent.train_step(batch_size=self.config["agent_config"]["batch_size"])
            if loss > 0:
                episode_loss += float(loss)

            for key, value in info.get("reward_components", {}).items():
                reward_breakdown_sum[key] = reward_breakdown_sum.get(key, 0.0) + float(value)
            for key, value in info.get("injection_stats", {}).items():
                total_injected[key] = total_injected.get(key, 0) + int(value)

            for tl_id, diag in info.get("junction_diagnostics", {}).items():
                if tl_id not in junction_metrics:
                    continue
                bucket = junction_metrics[tl_id]

                for lane_id, cnt in diag.get("emergency_detected_by_lane", {}).items():
                    bucket["emergency_detected_by_lane"][lane_id] += int(cnt)
                for lane_id, cnt in diag.get("normal_detected_by_lane", {}).items():
                    bucket["normal_detected_by_lane"][lane_id] += int(cnt)

                ped_now = int(diag.get("pedestrians_detected", 0))
                bucket["pedestrians_detected_total"] += ped_now
                bucket["pedestrians_detected_max"] = max(bucket["pedestrians_detected_max"], ped_now)

                bucket["green_change_checks"] = int(diag.get("green_change_checks", bucket["green_change_checks"]))
                bucket["green_change_drops"] = int(diag.get("green_change_drops", bucket["green_change_drops"]))
                bucket["green_change_left_vehicle_drop_rate"] = float(
                    diag.get("green_change_left_vehicle_drop_rate", bucket["green_change_left_vehicle_drop_rate"])
                )

                bucket["emergency_stops"] += int(diag.get("emergency_stops", 0))
                bucket["emergency_passed_without_stop"] = max(
                    bucket["emergency_passed_without_stop"],
                    int(diag.get("emergency_passed_without_stop", 0)),
                )

                lane_name = diag.get("most_priority_lane", "")
                if lane_name:
                    bucket["most_priority_lane_histogram"][lane_name] += 1

                bucket["ped_green_when_empty"] = max(
                    bucket["ped_green_when_empty"],
                    int(diag.get("ped_green_when_empty_total", 0)),
                )

            state = next_state
            total_reward += float(reward)
            step_count += 1

            if step % 100 == 0:
                print(f"Episode {episode}, Step {step}: Reward={reward:.3f}, Loss={loss:.4f}")

            if done:
                break

        metrics = {
            "reward_breakdown": reward_breakdown_sum,
            "injected": total_injected,
            "junction_diagnostics": {
                tl_id: {
                    "emergency_detected_by_lane": dict(vals["emergency_detected_by_lane"]),
                    "normal_detected_by_lane": dict(vals["normal_detected_by_lane"]),
                    "pedestrians_detected_total": int(vals["pedestrians_detected_total"]),
                    "pedestrians_detected_max": int(vals["pedestrians_detected_max"]),
                    "green_change_checks": int(vals["green_change_checks"]),
                    "green_change_drops": int(vals["green_change_drops"]),
                    "green_change_left_vehicle_drop_rate": float(vals["green_change_left_vehicle_drop_rate"]),
                    "emergency_stops": int(vals["emergency_stops"]),
                    "emergency_passed_without_stop": int(vals["emergency_passed_without_stop"]),
                    "most_priority_lane": (
                        max(vals["most_priority_lane_histogram"], key=vals["most_priority_lane_histogram"].get)
                        if vals["most_priority_lane_histogram"]
                        else ""
                    ),
                    "ped_green_when_empty": int(vals["ped_green_when_empty"]),
                }
                for tl_id, vals in junction_metrics.items()
            },
        }
        return total_reward, (episode_loss / max(step_count, 1)), step_count, metrics

    def train(self) -> None:
        print(f"Starting training for {self.config['num_episodes']} episodes...")
        print("=" * 50)
        start_time = time.time()

        try:
            for episode in range(1, self.config["num_episodes"] + 1):
                episode_reward, avg_loss, episode_length, metrics = self.train_episode(episode)

                self.episode_rewards.append(float(episode_reward))
                self.episode_lengths.append(int(episode_length))
                self.losses.append(float(avg_loss))

                if episode % self.config["log_frequency"] == 0:
                    print(f"\nEpisode {episode} Summary:")
                    print(f"  Total Reward: {episode_reward:.2f}")
                    print(f"  Avg Loss: {avg_loss:.4f}")
                    print(f"  Episode Length: {episode_length}")
                    print(f"  Epsilon: {self.multi_agent.agents[self.agent_ids[0]].epsilon:.3f}")
                    print(f"  Injected: {metrics['injected']}")
                    print("-" * 30)

                self.save_episode_training_log(
                    episode=episode,
                    reward=episode_reward,
                    avg_loss=avg_loss,
                    episode_length=episode_length,
                    episode_metrics=metrics,
                )

                if episode % self.config["save_frequency"] == 0:
                    model_dir = f"models/episode_{episode}"
                    self.multi_agent.save_models(model_dir)
                    print(f"Models saved to {model_dir}")
                    self.save_training_progress(episode)

            training_time = time.time() - start_time
            print(f"\nTraining completed in {training_time:.2f} seconds")
            self.save_final_results()

        finally:
            self.multi_agent.close()
            self.env.close()

    def save_training_progress(self, episode: int) -> None:
        epsilon_values = {agent_id: agent.epsilon for agent_id, agent in self.multi_agent.agents.items()}
        progress = {
            "episode": episode,
            "rewards": self.episode_rewards,
            "lengths": self.episode_lengths,
            "losses": self.losses,
            "epsilon": epsilon_values,
            "timestamp": datetime.now().isoformat(),
        }

        progress_path = f"logs/training_progress_ep{episode}.json"
        with open(progress_path, "w") as f:
            json.dump(progress, f, indent=2)

    def save_episode_training_log(
        self,
        episode: int,
        reward: float,
        avg_loss: float,
        episode_length: int,
        episode_metrics: dict,
    ) -> None:
        payload = {
            "episode": int(episode),
            "reward": float(reward),
            "avg_loss": float(avg_loss),
            "episode_length": int(episode_length),
            "epsilon": {aid: float(ag.epsilon) for aid, ag in self.multi_agent.agents.items()},
            "reward_breakdown": episode_metrics.get("reward_breakdown", {}),
            "injected": episode_metrics.get("injected", {}),
            "junction_diagnostics": episode_metrics.get("junction_diagnostics", {}),
            "timestamp": datetime.now().isoformat(),
        }

        path = f"logs/training/episode_{episode}.json"
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    def save_final_results(self) -> None:
        final_dir = "models/final"
        self.multi_agent.save_models(final_dir)
        self.plot_training_progress()

        summary = {
            "total_episodes": len(self.episode_rewards),
            "final_epsilon": self.multi_agent.agents[self.agent_ids[0]].epsilon,
            "avg_final_reward": (
                np.mean(self.episode_rewards[-10:]) if len(self.episode_rewards) >= 10 else np.mean(self.episode_rewards)
            ),
            "config": self.config,
        }

        summary_path = "logs/training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

    def plot_training_progress(self) -> None:
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))

        axes[0, 0].plot(self.episode_rewards)
        axes[0, 0].set_title("Episode Rewards")
        axes[0, 0].set_xlabel("Episode")
        axes[0, 0].set_ylabel("Total Reward")
        axes[0, 0].grid(True, alpha=0.3)

        window = min(10, max(1, len(self.episode_rewards) // 10))
        if len(self.episode_rewards) >= window and window > 1:
            moving_avg = np.convolve(self.episode_rewards, np.ones(window) / window, mode="valid")
            axes[0, 1].plot(moving_avg)
            axes[0, 1].set_title(f"Moving Average of Rewards (window={window})")
            axes[0, 1].set_xlabel("Episode")
            axes[0, 1].set_ylabel("Average Reward")
            axes[0, 1].grid(True, alpha=0.3)

        axes[1, 0].plot(self.episode_lengths)
        axes[1, 0].set_title("Episode Lengths")
        axes[1, 0].set_xlabel("Episode")
        axes[1, 0].set_ylabel("Steps")
        axes[1, 0].grid(True, alpha=0.3)

        if self.losses:
            axes[1, 1].plot(self.losses)
            axes[1, 1].set_title("Training Loss")
            axes[1, 1].set_xlabel("Episode")
            axes[1, 1].set_ylabel("Loss")
            axes[1, 1].grid(True, alpha=0.3)

        plt.tight_layout()
        plot_path = "logs/training_progress.png"
        plt.savefig(plot_path, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"Training plots saved to {plot_path}")


def main() -> None:
    print("=" * 60)
    print("MARL Traffic Signal Control with VDN - Training")
    print("=" * 60)

    trainer = Trainer()
    trainer.train()

    print("\nTraining complete!")
    print("Next steps:")
    print("1. Check 'models/final/' for trained models")
    print("2. Check 'logs/training/' for per-episode training data")
    print("3. Run evaluation script to test trained models")


if __name__ == "__main__":
    main()
