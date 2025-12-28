import os
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
        self.mixer = VDNMixer(self.num_agents)
        
        self.target_update_freq = config.get('target_update_freq', 10)

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
        
        device = self.agents[self.agent_ids[0]].device
        # Convert to tensors
        states_tensor = torch.FloatTensor(states_batch).to(device)  # [batch, num_agents, state_dim]
        actions_tensor = torch.LongTensor(actions_batch).to(device)  # [batch, num_agents]
        rewards_tensor = torch.FloatTensor(rewards_batch).to(device)  # [batch]
        next_states_tensor = torch.FloatTensor(next_states_batch).to(device)  # [batch, num_agents, state_dim]
        dones_tensor = torch.FloatTensor(dones_batch).to(device)  # [batch]
        
         # Get selected Q-values for each agent
        # Get selected Q-values for each agent
        selected_qs = []
        for i, agent_id in enumerate(self.agent_ids):
            agent_states = states_tensor[:, i, :]
            agent_actions = actions_tensor[:, i]
            agent_q = self.agents[agent_id].q_network(agent_states)
            selected_q = agent_q.gather(1, agent_actions.unsqueeze(1)).squeeze(1)
            selected_qs.append(selected_q)

        # Stack: [batch_size, num_agents]
        selected_qs_tensor = torch.stack(selected_qs, dim=1)  # Remove .squeeze(-1)
        q_tot = self.mixer(selected_qs_tensor)  # Should output [batch_size]

        # Target calculation - USE MIXER CONSISTENTLY
        with torch.no_grad():
            target_qs = []
            for i, agent_id in enumerate(self.agent_ids):
                next_agent_states = next_states_tensor[:, i, :]
                target_q = self.agents[agent_id].target_network(next_agent_states)
                max_target_q = torch.max(target_q, dim=1)[0]  # [batch_size]
                target_qs.append(max_target_q)
            
            # Stack: [batch_size, num_agents] and use mixer
            target_qs_tensor = torch.stack(target_qs, dim=1)
            target_q_tot = self.mixer(target_qs_tensor)  # [batch_size]
            
            target = rewards_tensor + (1 - dones_tensor) * self.agents[self.agent_ids[0]].gamma * target_q_tot

        # Calculate loss
        loss = nn.MSELoss()(q_tot, target)
        
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
        if self.training_step % self.target_update_freq == 0:
            for agent in self.agents.values():
                agent.target_network.load_state_dict(agent.q_network.state_dict())

        if batch_size > 0:  # Only if we actually trained
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
        """Load all agent models - returns success flag"""
        try:
            for agent_id, agent in self.agents.items():
                model_path = f"{path}/{agent_id}_model.pth"
                if os.path.exists(model_path):
                    agent.load(model_path)
                    print(f"  Loaded model for {agent_id}")
                else:
                    print(f"  Warning: Model not found for {agent_id}: {model_path}")
                    return False
            return True
        except Exception as e:
            print(f"Error loading models: {e}")
            return False

    def get_enhanced_state(self, base_state: np.ndarray, agent_id: str) -> np.ndarray:
        """Enhance state with neighbor information - VERIFIED"""
        # Get messages from neighbors
        messages = self.communications[agent_id].get_neighbor_messages()
        
        # Extract neighbor information
        neighbor_info = []
        for neighbor_id, message in messages.items():
            if "data" in message and "queue" in message["data"]:
                neighbor_info.extend(message["data"]["queue"])  # Queue lengths - 4 values
                neighbor_info.append(message["data"].get("current_phase", 0))  # 1 value
                neighbor_info.append(message["data"].get("intended_action", 0))  # 1 value
        
        # Pad if no neighbor info or not enough
        while len(neighbor_info) < 10:
            neighbor_info.append(0)
        
        # Take exactly 10 neighbor features
        neighbor_features = np.array(neighbor_info[:10])
        
        # Verify dimensions
        if len(base_state) != 13:
            print(f"WARNING: Base state has {len(base_state)} dims, expected 13")
        if len(neighbor_features) != 10:
            print(f"WARNING: Neighbor features has {len(neighbor_features)} dims, expected 10")
        
        # Combine base state with neighbor info
        enhanced_state = np.concatenate([base_state, neighbor_features])
        
        # Final verification
        if len(enhanced_state) != 23:
            print(f"ERROR: Enhanced state has {len(enhanced_state)} dims, expected 23!")
            print(f"  Base: {len(base_state)}, Neighbor: {len(neighbor_features)}")
        
        return enhanced_state
    
    def get_intended_action(self, base_state: np.ndarray, agent_id: str) -> int:
        """Get action from base state (for communication)"""
        # You need a way to get Q-values from base state only
        # Option 1: Keep a separate base-state network
        # Option 2: Pad base state with zeros for neighbor features
        base_state_tensor = torch.FloatTensor(base_state).unsqueeze(0).to(self.device)
        
        # For now, just use the base state (this might not work well)
        # Actually, let's create a temporary enhanced state with zeros for neighbors
        temp_enhanced = np.concatenate([base_state, np.zeros(10)])
        return self.agents[agent_id].act(temp_enhanced, explore=False)

    def act_with_coordination(self, states: Dict[str, np.ndarray], training_mode: bool = True) -> Dict[str, int]:
        """Get actions with coordination between agents - FIXED VERSION"""
        actions = {}
        
        # Phase 1: Exchange information
        for agent_id, state in states.items():
            # For intended_action, we need to use current state (no neighbor info yet)
            # Create a temporary enhanced state with zeros for neighbor info
            temp_neighbor_info = [0] * 10  # 10 zero features for neighbors
            temp_enhanced_state = np.concatenate([state, np.array(temp_neighbor_info)])
            
            # Get intended action from temporary enhanced state
            intended_action = self.agents[agent_id].act(temp_enhanced_state, explore=False)
            
            # Prepare state info to send
            state_info = {
                "queue": state[:4].tolist(),  # First 4 are queue lengths
                "current_phase": int(state[8] * 8),  # Phase index
                "intended_action": intended_action  # Use the action from temp enhanced state
            }
            
            # Send to neighbors
            self.communications[agent_id].send_state(state_info)
        
        # Small delay for message propagation
        time.sleep(0.01)
        
        # Phase 2: Select actions with ACTUAL neighbor info
        for agent_id, state in states.items():
            # Enhance state with REAL neighbor info (from messages just sent)
            enhanced_state = self.get_enhanced_state(state, agent_id)
            
            # Select action with full enhanced state
            action = self.agents[agent_id].act(enhanced_state, explore=training_mode)
            actions[agent_id] = action
            
            # Store for next step
            self.previous_actions[agent_id] = action
        
        return actions

    