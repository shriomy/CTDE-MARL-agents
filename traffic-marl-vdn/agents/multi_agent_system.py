import os
import time
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn

from agents.communication import AgentCommunication
from agents.dqn_agent import DQNAgent
from agents.vdn_mixer import CentralizedBuffer, VDNMixer


class MultiAgentSystem:
    """Coordinates MARL agents with VDN under CTDE."""

    def __init__(
        self,
        agent_ids: List[str],
        base_state_dim: int = None,
        action_dim: int = 5,
        config: dict = None,
        state_dim: int = None,
    ):
        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)
        self.config = config or {}

        # Backward compatibility: older callers passed full state_dim directly.
        inferred_base = base_state_dim
        if inferred_base is None and state_dim is not None:
            neighbor_hint = int(self.config.get("neighbor_feature_dim", 8))
            inferred_base = max(1, int(state_dim) - neighbor_hint)
        if inferred_base is None:
            raise ValueError("base_state_dim or state_dim must be provided")

        self.base_state_dim = int(inferred_base)
        self.action_dim = action_dim

        self.neighbor_feature_dim = int(config.get("neighbor_feature_dim", 8))
        self.state_dim = self.base_state_dim + self.neighbor_feature_dim

        self.agents = {
            agent_id: DQNAgent(self.state_dim, action_dim, agent_id, config) for agent_id in self.agent_ids
        }
        self.mixer = VDNMixer(self.num_agents)
        self.target_update_freq = int(config.get("target_update_freq", 10))
        self.central_buffer = CentralizedBuffer(int(config.get("central_buffer_size", 50000)))

        self.communication_enabled = bool(config.get("enable_communication", True))
        self.neighbor_map = self._build_neighbor_map(config.get("neighbor_map", {}))

        self.communications = {}
        for agent_id in self.agent_ids:
            neighbors = self.neighbor_map.get(agent_id, [])
            self.communications[agent_id] = AgentCommunication(
                agent_id=agent_id,
                neighbor_ids=neighbors,
                config=config,
            )

        self.previous_actions = {agent_id: 4 for agent_id in self.agent_ids}
        self.training_step = 0
        self.last_enhanced_states = {
            agent_id: np.zeros(self.state_dim, dtype=np.float32) for agent_id in self.agent_ids
        }

    def _build_neighbor_map(self, user_neighbor_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
        if user_neighbor_map:
            return {
                agent: [n for n in neighbors if n in self.agent_ids]
                for agent, neighbors in user_neighbor_map.items()
                if agent in self.agent_ids
            }

        default_map = {
            "J1": ["J4", "J8"],
            "J4": ["J1"],
            "J8": ["J1"],
        }
        return {agent: [n for n in default_map.get(agent, []) if n in self.agent_ids] for agent in self.agent_ids}

    def _state_summary(self, state: np.ndarray, intended_action: int) -> Dict[str, float]:
        """Compact message payload for decentralized coordination."""
        arr = np.asarray(state, dtype=np.float32)
        queue_pressure = float(np.mean(arr[0: min(6, len(arr))])) if len(arr) > 0 else 0.0
        priority_pressure = float(np.mean(arr[3: min(18, len(arr)):5])) if len(arr) >= 4 else 0.0
        emergency_pressure = float(np.mean(arr[4: min(19, len(arr)):5])) if len(arr) >= 5 else 0.0

        return {
            "queue_pressure": queue_pressure,
            "priority_pressure": priority_pressure,
            "emergency_pressure": emergency_pressure,
            "intended_action": float(intended_action),
            "timestamp": time.time(),
        }

    def _neighbor_features_from_messages(self, agent_id: str) -> np.ndarray:
        msgs = self.communications[agent_id].get_neighbor_messages() if self.communication_enabled else {}

        if not msgs:
            return np.zeros(self.neighbor_feature_dim, dtype=np.float32)

        queue_vals = []
        priority_vals = []
        emergency_vals = []
        action_vals = []

        for payload in msgs.values():
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            queue_vals.append(float(data.get("queue_pressure", 0.0)))
            priority_vals.append(float(data.get("priority_pressure", 0.0)))
            emergency_vals.append(float(data.get("emergency_pressure", 0.0)))
            action_vals.append(int(data.get("intended_action", 4)))

        action_hist = np.zeros(5, dtype=np.float32)
        for a in action_vals:
            if 0 <= a < 5:
                action_hist[a] += 1.0
        if len(action_vals) > 0:
            action_hist /= float(len(action_vals))

        features = np.array(
            [
                float(np.mean(queue_vals)) if queue_vals else 0.0,
                float(np.max(queue_vals)) if queue_vals else 0.0,
                float(np.mean(priority_vals)) if priority_vals else 0.0,
                float(np.max(priority_vals)) if priority_vals else 0.0,
                float(np.mean(emergency_vals)) if emergency_vals else 0.0,
                float(np.max(emergency_vals)) if emergency_vals else 0.0,
                float(len(msgs)) / max(1.0, float(len(self.neighbor_map.get(agent_id, [])))),
                action_hist[1] + action_hist[2] + action_hist[3],
            ],
            dtype=np.float32,
        )

        if len(features) < self.neighbor_feature_dim:
            features = np.concatenate([features, np.zeros(self.neighbor_feature_dim - len(features), dtype=np.float32)])
        return features[: self.neighbor_feature_dim]

    def _broadcast_state_intents(self, states: Dict[str, np.ndarray], training_mode: bool) -> None:
        if not self.communication_enabled:
            return

        for agent_id, state in states.items():
            padded = np.concatenate([state, np.zeros(self.neighbor_feature_dim, dtype=np.float32)])
            intended = self.agents[agent_id].act(padded, explore=training_mode)
            payload = self._state_summary(state, intended)
            try:
                self.communications[agent_id].send_state(payload)
            except Exception:
                pass

        # Short sync delay so subscriber threads can pick up recent messages.
        time.sleep(0.01)

    def get_enhanced_state(self, base_state: np.ndarray, agent_id: str) -> np.ndarray:
        neighbor_features = self._neighbor_features_from_messages(agent_id)
        enhanced = np.concatenate([np.asarray(base_state, dtype=np.float32), neighbor_features]).astype(np.float32)
        return enhanced

    def act_with_coordination(self, states: Dict[str, np.ndarray], training_mode: bool = True) -> Dict[str, int]:
        actions = {}

        self._broadcast_state_intents(states, training_mode=training_mode)

        for agent_id in self.agent_ids:
            enhanced = self.get_enhanced_state(states[agent_id], agent_id)
            self.last_enhanced_states[agent_id] = enhanced
            action = self.agents[agent_id].act(enhanced, explore=training_mode)
            actions[agent_id] = int(action)
            self.previous_actions[agent_id] = int(action)

        return actions

    def build_next_enhanced_states(self, next_states: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        """Generate enhanced next states for replay tuples."""
        self._broadcast_state_intents(next_states, training_mode=False)
        out = {}
        for agent_id in self.agent_ids:
            out[agent_id] = self.get_enhanced_state(next_states[agent_id], agent_id)
        return out

    def train_step(self, batch_size: int = 32) -> Tuple[float, float]:
        if len(self.central_buffer) < batch_size:
            return 0.0, 0.0

        states_batch, actions_batch, rewards_batch, next_states_batch, dones_batch = self.central_buffer.sample(batch_size)

        device = self.agents[self.agent_ids[0]].device
        states_tensor = torch.FloatTensor(states_batch).to(device)
        actions_tensor = torch.LongTensor(actions_batch).to(device)
        rewards_tensor = torch.FloatTensor(rewards_batch).to(device)
        rewards_sum = rewards_tensor.sum(dim=1)
        next_states_tensor = torch.FloatTensor(next_states_batch).to(device)
        dones_tensor = torch.FloatTensor(dones_batch).to(device)

        selected_qs = []
        for i, agent_id in enumerate(self.agent_ids):
            agent_states = states_tensor[:, i, :]
            agent_actions = actions_tensor[:, i]
            q_values = self.agents[agent_id].q_network(agent_states)
            selected_q = q_values.gather(1, agent_actions.unsqueeze(1)).squeeze(1)
            selected_qs.append(selected_q)

        selected_qs_tensor = torch.stack(selected_qs, dim=1)
        q_tot = self.mixer(selected_qs_tensor)

        with torch.no_grad():
            target_qs = []
            for i, agent_id in enumerate(self.agent_ids):
                agent_next_states = next_states_tensor[:, i, :]
                target_q_values = self.agents[agent_id].target_network(agent_next_states)
                target_qs.append(torch.max(target_q_values, dim=1)[0])

            target_qs_tensor = torch.stack(target_qs, dim=1)
            target_q_tot = self.mixer(target_qs_tensor)
            gamma = self.agents[self.agent_ids[0]].gamma
            target = rewards_sum + (1.0 - dones_tensor) * gamma * target_q_tot

        loss = nn.MSELoss()(q_tot, target)

        for agent in self.agents.values():
            agent.optimizer.zero_grad()

        loss.backward()

        total_norm = 0.0
        grad_clip = float(self.config.get("grad_clip", 1.0))
        for agent in self.agents.values():
            torch.nn.utils.clip_grad_norm_(agent.q_network.parameters(), grad_clip)
            agent.optimizer.step()
            for param in agent.q_network.parameters():
                if param.grad is not None:
                    total_norm += float(param.grad.data.norm(2).item())

        self.training_step += 1
        if self.training_step % self.target_update_freq == 0:
            for agent in self.agents.values():
                agent.target_network.load_state_dict(agent.q_network.state_dict())

        for agent in self.agents.values():
            agent.epsilon = max(agent.epsilon_min, agent.epsilon * agent.epsilon_decay)

        return float(loss.item()), float(total_norm)

    def remember(self, experience: tuple) -> None:
        self.central_buffer.add(experience)

    def save_models(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        for agent_id, agent in self.agents.items():
            agent.save(f"{path}/{agent_id}_model.pth")

    def load_models(self, path: str) -> bool:
        try:
            for agent_id, agent in self.agents.items():
                model_path = f"{path}/{agent_id}_model.pth"
                if os.path.exists(model_path):
                    agent.load(model_path)
                else:
                    return False
            return True
        except Exception:
            return False

    def close(self) -> None:
        for comm in self.communications.values():
            try:
                comm.close()
            except Exception:
                pass

