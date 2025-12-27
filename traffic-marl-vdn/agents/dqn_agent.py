import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from collections import deque, namedtuple
import random

# Define experience tuple
Experience = namedtuple('Experience', 
                       ['state', 'action', 'reward', 'next_state', 'done'])

class DQNAgent:
    """Deep Q-Network Agent for single intersection"""
    
    def __init__(self, state_dim: int, action_dim: int, agent_id: str, config: dict):
        self.agent_id = agent_id
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config
        
        # Neural network
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.q_network = self._build_network().to(self.device)
        self.target_network = self._build_network().to(self.device)
        self.target_network.load_state_dict(self.q_network.state_dict())
        
        # Optimizer
        self.optimizer = optim.Adam(self.q_network.parameters(), 
                                   lr=config.get('learning_rate', 0.001))
        
        # Experience replay buffer
        self.memory = deque(maxlen=config.get('buffer_size', 10000))
        
        # Training parameters
        self.gamma = config.get('gamma', 0.99)  # Discount factor
        self.epsilon = config.get('epsilon_start', 1.0)  # Exploration rate
        self.epsilon_min = config.get('epsilon_min', 0.01)
        self.epsilon_decay = config.get('epsilon_decay', 0.995)
        self.batch_size = config.get('batch_size', 32)
        self.target_update_freq = config.get('target_update_freq', 10)
        self.training_step = 0
        
    def _build_network(self) -> nn.Module:
        """Build the Q-network architecture"""
        return nn.Sequential(
            nn.Linear(self.state_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, self.action_dim)
        )
    
    def act(self, state: np.ndarray, explore: bool = True) -> int:
        """Select action using ε-greedy policy"""
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        
        # Exploration: random action
        if explore and random.random() < self.epsilon:
            return random.randrange(self.action_dim)
        
        # Exploitation: best action from Q-network
        with torch.no_grad():
            q_values = self.q_network(state_tensor)
            return torch.argmax(q_values).item()
    
    def remember(self, experience: Experience):
        """Store experience in replay buffer"""
        self.memory.append(experience)
    
    def train(self):
        """Train the agent using experience replay"""
        if len(self.memory) < self.batch_size:
            return 0
        
        # Sample batch from replay buffer
        batch = random.sample(self.memory, self.batch_size)
        batch = Experience(*zip(*batch))
        
        # Convert to tensors
        states = torch.FloatTensor(np.array(batch.state)).to(self.device)
        actions = torch.LongTensor(batch.action).unsqueeze(1).to(self.device)
        rewards = torch.FloatTensor(batch.reward).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(np.array(batch.next_state)).to(self.device)
        dones = torch.FloatTensor(batch.done).unsqueeze(1).to(self.device)
        
        # Current Q-values
        current_q = self.q_network(states).gather(1, actions)
        
        # Next Q-values from target network
        with torch.no_grad():
            next_q = self.target_network(next_states).max(1, keepdim=True)[0]
            target_q = rewards + (1 - dones) * self.gamma * next_q
        
        # Calculate loss
        loss = nn.MSELoss()(current_q, target_q)
        
        # Optimize
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)  # Gradient clipping
        self.optimizer.step()
        
        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        
        # Update target network periodically
        self.training_step += 1
        if self.training_step % self.target_update_freq == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())
        
        return loss.item()
    
    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for all actions"""
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad():
            q_values = self.q_network(state_tensor).cpu().numpy()[0]
        return q_values
    
    def save(self, path: str):
        """Save agent parameters"""
        torch.save({
            'q_network_state_dict': self.q_network.state_dict(),
            'target_network_state_dict': self.target_network.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epsilon': self.epsilon,
            'training_step': self.training_step,
        }, path)
    
    def load(self, path: str):
        """Load agent parameters"""
        checkpoint = torch.load(path, map_location=self.device)
        self.q_network.load_state_dict(checkpoint['q_network_state_dict'])
        self.target_network.load_state_dict(checkpoint['target_network_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.epsilon = checkpoint['epsilon']
        self.training_step = checkpoint['training_step']