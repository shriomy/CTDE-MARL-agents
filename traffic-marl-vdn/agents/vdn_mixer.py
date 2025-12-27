import torch
import torch.nn as nn
import numpy as np
from typing import List, Dict

class VDNMixer(nn.Module):
    """Value Decomposition Network Mixer - Simplified"""
    
    def __init__(self, num_agents: int):
        super().__init__()
        self.num_agents = num_agents
        # VDN has no learnable parameters - it's just a sum
        
    def forward(self, agent_qs: torch.Tensor) -> torch.Tensor:
        """
        VDN: Q_tot = Σ Q_i (for chosen actions)
        
        Args:
            agent_qs: Tensor of shape [batch_size, num_agents]
                    where each element is Q_i(s_i, a_i) for chosen action
                    
        Returns:
            q_tot: Tensor of shape [batch_size]
        """
        return torch.sum(agent_qs, dim=1)
    
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