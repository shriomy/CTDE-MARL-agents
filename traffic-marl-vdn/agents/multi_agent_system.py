import torch
import torch.nn as nn
import numpy as np
from typing import Dict, List, Tuple
import zmq
import threading
import time
from collections import defaultdict
from agents.communication import AgentCommunication

from agents.dqn_agent import DQNAgent
from agents.vdn_mixer import VDNMixer, CentralizedBuffer

class MultiAgentSystem:
    """Coordinates multiple agents using VDN architecture"""
    
    def __init__(self, agent_ids: List[str], state_dim: int, action_dim: int, config: dict):
        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config
        
        # Create individual agents
        self.agents = {}
        for agent_id in agent_ids:
            self.agents[agent_id] = DQNAgent(state_dim, action_dim, agent_id, config)
        
        # Create VDN mixer
        self.mixer = VDNMixer(self.num_agents, state_dim, config)
        
        # Centralized replay buffer
        self.central_buffer = CentralizedBuffer(config.get('central_buffer_size', 10000))
        
        # Communication setup (for decentralized execution)
        self.communication_enabled = config.get('enable_communication', True)
        
        # Training parameters
        self.training_step = 0

        # Define neighbor relationships (who talks to whom)
        self.neighbor_map = {
        "J1_center": ["J2_center"],  # J1 talks to J2
        "J2_center": ["J1_center"]   # J2 talks to J1
        }

         # Initialize communication for each agent
        self.communications = {}
        for agent_id in agent_ids:
            neighbors = self.neighbor_map.get(agent_id, [])
            self.communications[agent_id] = AgentCommunication(
                agent_id=agent_id,
                neighbor_ids=neighbors,
                config=config
            )
        
        # Track previous actions for coordination
        self.previous_actions = {agent_id: 0 for agent_id in agent_ids}
        
    def setup_communication(self):
        """Setup ZeroMQ communication between agents"""
        context = zmq.Context()
        
        # Each agent has a publisher and subscriber
        self.publishers = {}
        self.subscribers = {}
        
        base_port = 5555
        for i, agent_id in enumerate(self.agent_ids):
            # Publisher for this agent
            publisher = context.socket(zmq.PUB)
            publisher.bind(f"tcp://*:{base_port + i}")
            self.publishers[agent_id] = publisher
            
            # Subscribers to other agents
            subscriber = context.socket(zmq.SUB)
            for j, other_id in enumerate(self.agent_ids):
                if other_id != agent_id:
                    subscriber.connect(f"tcp://localhost:{base_port + j}")
                    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
            self.subscribers[agent_id] = subscriber
        
        print(f"Communication setup complete on ports {base_port}-{base_port + len(self.agent_ids)-1}")
    
    def send_message(self, sender_id: str, message: dict):
        """Send message from one agent to others via AgentCommunication"""
        if not self.communication_enabled:
            return
        comm = self.communications.get(sender_id)
        if comm is None:
            return
        try:
            comm.publisher.send_json(message)
        except Exception:
            pass
    
    def receive_messages(self, receiver_id: str) -> List[dict]:
        """Receive messages for an agent via AgentCommunication"""
        if not self.communication_enabled:
            return []
        comm = self.communications.get(receiver_id)
        if comm is None:
            return []
        msgs = comm.get_neighbor_messages()  # dict of sender -> {data, timestamp}
        out = []
        for sender, payload in msgs.items():
            out.append({
                'sender': sender,
                'state': payload.get('data'),
                'timestamp': payload.get('timestamp')
            })
        return out
    
    def act(self, states: Dict[str, np.ndarray], training_mode: bool = True) -> Dict[str, int]:
        """Get actions from all agents"""
        actions = {}
        
        # Exchange information between agents
        if self.communication_enabled:
            for agent_id in self.agent_ids:
                # Send local state to neighbors using AgentCommunication API
                comm = self.communications.get(agent_id)
                if comm is not None:
                    state_info = {
                        'queue': states[agent_id][:4].tolist() if hasattr(states[agent_id], 'tolist') else list(states[agent_id][:4]),
                        'full_state': states[agent_id].tolist() if hasattr(states[agent_id], 'tolist') else list(states[agent_id]),
                        'timestamp': time.time()
                    }
                    try:
                        comm.send_state(state_info)
                    except Exception:
                        pass
        
        # Each agent selects action
        for agent_id, state in states.items():
            agent = self.agents[agent_id]
            
            # Receive messages from neighbors
            if self.communication_enabled:
                messages = self.receive_messages(agent_id)
                # Could incorporate neighbor info into state here
            
            # Select action
            action = agent.act(state, explore=training_mode)
            actions[agent_id] = action
        
        return actions
    
    def train_step(self, batch_size: int = 32):
        """Train all agents using centralized experience"""
        if len(self.central_buffer) < batch_size:
            return 0, 0
        
        # Sample batch from centralized buffer
        states_batch, actions_batch, rewards_batch, next_states_batch, dones_batch = \
            self.central_buffer.sample(batch_size)
        
        # Convert to tensors
        states_tensor = torch.FloatTensor(states_batch)  # [batch, num_agents, state_dim]
        actions_tensor = torch.LongTensor(actions_batch)  # [batch, num_agents]
        rewards_tensor = torch.FloatTensor(rewards_batch)  # [batch]
        next_states_tensor = torch.FloatTensor(next_states_batch)  # [batch, num_agents, state_dim]
        dones_tensor = torch.FloatTensor(dones_batch)  # [batch]
        
        # Get Q-values from all agents
        agent_qs = []
        target_qs = []
        
        for i, agent_id in enumerate(self.agent_ids):
            agent = self.agents[agent_id]
            
            # Current Q-values
            agent_states = states_tensor[:, i, :]
            agent_q = agent.q_network(agent_states)  # [batch, action_dim]
            agent_qs.append(agent_q.unsqueeze(1))  # [batch, 1, action_dim]
            
            # Target Q-values
            with torch.no_grad():
                next_agent_states = next_states_tensor[:, i, :]
                target_q = agent.target_network(next_agent_states)  # [batch, action_dim]
                target_qs.append(target_q.unsqueeze(1))  # [batch, 1, action_dim]
        
        # Stack Q-values
        agent_qs = torch.cat(agent_qs, dim=1)  # [batch, num_agents, action_dim]
        target_qs = torch.cat(target_qs, dim=1)  # [batch, num_agents, action_dim]
        
        # Get joint Q-values using VDN mixer
        joint_q = self.mixer(agent_qs)  # [batch, action_dim, action_dim, ...]
        
        # Get joint action indices
        # This is complex: we need to index joint_q with the joint actions
        # For 2 agents:
        if self.num_agents == 2:
            # Index joint Q-values with the actual joint actions
            batch_indices = torch.arange(batch_size)
            current_q = joint_q[batch_indices, actions_tensor[:, 0], actions_tensor[:, 1]]
        else:
            # General case
            current_q = joint_q
            for i in range(self.num_agents):
                current_q = current_q[batch_indices, actions_tensor[:, i]]
        
        # Target Q-values
        with torch.no_grad():
            # Get max over joint actions for next state
            next_joint_q = self.mixer(target_qs)  # [batch, action_dim, action_dim, ...]
            
            if self.num_agents == 2:
                # For 2 agents: max over both action dimensions
                max_next_q, _ = torch.max(torch.max(next_joint_q, dim=1)[0], dim=1)
            else:
                # General case: max over all action dimensions
                max_next_q = next_joint_q.max()
            
            target_q = rewards_tensor + (1 - dones_tensor) * self.agents[self.agent_ids[0]].gamma * max_next_q
        
        # Calculate loss
        loss = nn.MSELoss()(current_q, target_q)
        
        # Backpropagation
        for agent in self.agents.values():
            agent.optimizer.zero_grad()
        
        loss.backward()
        
        # Update all agents
        total_norm = 0
        for agent in self.agents.values():
            torch.nn.utils.clip_grad_norm_(agent.q_network.parameters(), 1.0)
            agent.optimizer.step()
            
            # Track gradient norm
            for param in agent.q_network.parameters():
                if param.grad is not None:
                    total_norm += param.grad.data.norm(2).item()
        
        # Update target networks periodically
        self.training_step += 1
        if self.training_step % 10 == 0:
            for agent in self.agents.values():
                agent.target_network.load_state_dict(agent.q_network.state_dict())

        for agent in self.agents.values():
            agent.epsilon = max(agent.epsilon_min, agent.epsilon * agent.epsilon_decay)
        
        return loss.item(), total_norm
    
    def remember(self, experience: tuple):
        """Store experience in centralized buffer"""
        self.central_buffer.add(experience)
    
    def save_models(self, path: str):
        """Save all agent models"""
        for agent_id, agent in self.agents.items():
            agent.save(f"{path}/{agent_id}_model.pth")
    
    def load_models(self, path: str):
        """Load all agent models"""
        for agent_id, agent in self.agents.items():
            agent.load(f"{path}/{agent_id}_model.pth")

    def get_enhanced_state(self, base_state: np.ndarray, agent_id: str) -> np.ndarray:
        """Enhance state with neighbor information"""
        # Get messages from neighbors
        messages = self.communications[agent_id].get_neighbor_messages()
        
        # Extract neighbor information
        neighbor_info = []
        for neighbor_id, message in messages.items():
            if "data" in message and "queue" in message["data"]:
                neighbor_info.extend(message["data"]["queue"])  # Queue lengths
                neighbor_info.append(message["data"].get("current_phase", 0))
                neighbor_info.append(message["data"].get("intended_action", 0))
        
        # Pad if no neighbor info
        if not neighbor_info:
            neighbor_info = [0] * 10  # 10 features from neighbor
        
        # Combine base state with neighbor info
        enhanced_state = np.concatenate([
            base_state,
            np.array(neighbor_info[:10])  # Take first 10 neighbor features
        ])
        
        return enhanced_state
    
    def act_with_coordination(self, states: Dict[str, np.ndarray], training_mode: bool = True) -> Dict[str, int]:
        """Get actions with coordination between agents"""
        actions = {}
        
        # Phase 1: Exchange information
        for agent_id, state in states.items():
            # Prepare state info to send
            state_info = {
                "queue": state[:4].tolist(),  # First 4 are queue lengths
                "current_phase": int(state[8] * 8),  # Phase index
                "intended_action": self.agents[agent_id].act(state, explore=False)
            }
            
            # Send to neighbors
            self.communications[agent_id].send_state(state_info)
        
        # Small delay for message propagation
        time.sleep(0.01)
        
        # Phase 2: Select actions with neighbor info
        for agent_id, state in states.items():
            # Enhance state with neighbor info
            enhanced_state = self.get_enhanced_state(state, agent_id)
            
            # Select action
            action = self.agents[agent_id].act(enhanced_state, explore=training_mode)
            actions[agent_id] = action
            
            # Store for next step
            self.previous_actions[agent_id] = action
        
        return actions

    