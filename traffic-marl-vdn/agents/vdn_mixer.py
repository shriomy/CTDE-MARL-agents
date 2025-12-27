import torch
import torch.nn as nn
import numpy as np
from typing import List, Dict

class VDNMixer(nn.Module):
    """Value Decomposition Network Mixer"""
    
    def __init__(self, num_agents: int, state_dim: int, config: dict):
        super().__init__()
        self.num_agents = num_agents
        self.state_dim = state_dim
        self.config = config
        
        # VDN is simple: just sum the Q-values
        # No learnable parameters in the basic VDN
        
    def forward(self, agent_qs: torch.Tensor, states: torch.Tensor = None) -> torch.Tensor:
        """
        Combine individual Q-values into joint Q-value
        
        Args:
            agent_qs: Tensor of shape [batch_size, num_agents, action_dim]
            states: Global state (not used in basic VDN, but kept for interface)
            
        Returns:
            joint_q: Tensor of shape [batch_size, action_dim, action_dim, ...] 
                    (joint action space)
        """
        # In VDN: Q_tot = sum(Q_i) for corresponding actions
        # We need to construct the joint Q-value table
        
        batch_size = agent_qs.shape[0]
        action_dim = agent_qs.shape[2]
        
        # Create joint Q-value tensor by summing over agents
        # This creates a tensor of shape [batch_size, action_dim, action_dim, ...]
        # with num_agent dimensions of size action_dim
        
        # For 2 agents, we can explicitly compute:
        if self.num_agents == 2:
            # Expand and sum: Q_tot(a1, a2) = Q1(a1) + Q2(a2)
            q1 = agent_qs[:, 0, :].unsqueeze(2)  # [batch, action_dim, 1]
            q2 = agent_qs[:, 1, :].unsqueeze(1)  # [batch, 1, action_dim]
            joint_q = q1 + q2  # [batch, action_dim, action_dim]
            
        else:
            # For more agents, use iterative expansion
            joint_q = agent_qs[:, 0, :].unsqueeze(-1)
            for i in range(1, self.num_agents):
                joint_q = joint_q.unsqueeze(-1) + agent_qs[:, i, :].unsqueeze(1)
                # Reshape to add new dimension
            
        return joint_q
    
    def get_individual_gradients(self, total_loss: torch.Tensor, agent_qs: torch.Tensor):
        """
        In VDN, gradients flow directly to individual Q-networks
        because Q_tot = sum(Q_i)
        """
        # Gradients automatically flow through the sum operation
        pass

class CentralizedBuffer:
    """Centralized replay buffer for multi-agent experiences"""
    
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.buffer = []
        
    def add(self, experience: tuple):
        """Add experience: (states, joint_actions, reward, next_states, done)"""
        if len(self.buffer) >= self.capacity:
            self.buffer.pop(0)
        self.buffer.append(experience)
    
    def sample(self, batch_size: int):
        """Sample batch of experiences"""
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        batch = [self.buffer[i] for i in indices]
        
        # Separate components
        states_batch = np.array([exp[0] for exp in batch])
        actions_batch = np.array([exp[1] for exp in batch])
        rewards_batch = np.array([exp[2] for exp in batch])
        next_states_batch = np.array([exp[3] for exp in batch])
        dones_batch = np.array([exp[4] for exp in batch])
        
        return (states_batch, actions_batch, rewards_batch, 
                next_states_batch, dones_batch)
    
    def __len__(self):
        return len(self.buffer)