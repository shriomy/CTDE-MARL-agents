import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
import pandas as pd

class TrainingVisualizer:
    """Visualize training progress in real-time"""
    
    def __init__(self):
        self.fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 8))
        self.fig.suptitle('MARL Traffic Control Training', fontsize=16)
        
        # Initialize plots
        self.reward_plot, = ax1.plot([], [], 'b-', label='Episode Reward')
        self.avg_reward_plot, = ax1.plot([], [], 'r-', label='Moving Avg')
        ax1.set_title('Training Rewards')
        ax1.set_xlabel('Episode')
        ax1.set_ylabel('Total Reward')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Queue lengths plot
        self.queue_data = {'J1': [], 'J2': []}
        self.queue_lines = {
            'J1': ax2.plot([], [], 'b-', label='J1 Queue')[0],
            'J2': ax2.plot([], [], 'r-', label='J2 Queue')[0]
        }
        ax2.set_title('Queue Lengths')
        ax2.set_xlabel('Step')
        ax2.set_ylabel('Queue Length')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # Action distribution
        self.action_bars = ax3.bar(range(4), [0]*4, alpha=0.7)
        ax3.set_title('Action Distribution')
        ax3.set_xlabel('Action')
        ax3.set_ylabel('Frequency')
        ax3.set_xticks(range(4))
        ax3.set_xticklabels(['Extend', 'NS Green', 'EW Green', 'Emergency'])
        
        # Communication metrics
        self.comm_plot, = ax4.plot([], [], 'g-', label='Messages/sec')
        ax4.set_title('Communication Rate')
        ax4.set_xlabel('Episode')
        ax4.set_ylabel('Messages per second')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        # Data storage
        self.episode_rewards = []
        self.queue_history = {'J1': [], 'J2': []}
        self.action_counts = [0, 0, 0, 0]
        self.comm_rates = []
        
        plt.tight_layout()
    
    def update(self, episode_data: dict):
        """Update plots with new data"""
        episode = episode_data['episode']
        reward = episode_data['reward']
        queues = episode_data['queues']
        actions = episode_data['actions']
        comm_rate = episode_data.get('comm_rate', 0)
        
        # Update rewards
        self.episode_rewards.append(reward)
        self.reward_plot.set_data(range(len(self.episode_rewards)), self.episode_rewards)
        
        # Moving average
        if len(self.episode_rewards) > 10:
            moving_avg = np.convolve(self.episode_rewards, np.ones(10)/10, mode='valid')
            self.avg_reward_plot.set_data(range(10, len(self.episode_rewards)+1), moving_avg)
        
        # Update queues
        self.queue_history['J1'].append(queues['J1'])
        self.queue_history['J2'].append(queues['J2'])
        
        self.queue_lines['J1'].set_data(range(len(self.queue_history['J1'])), self.queue_history['J1'])
        self.queue_lines['J2'].set_data(range(len(self.queue_history['J2'])), self.queue_history['J2'])
        
        # Update action counts
        for action in actions:
            if 0 <= action < 4:
                self.action_counts[action] += 1
        
        total = sum(self.action_counts)
        if total > 0:
            for i, bar in enumerate(self.action_bars):
                bar.set_height(self.action_counts[i] / total * 100)
        
        # Update communication rate
        self.comm_rates.append(comm_rate)
        self.comm_plot.set_data(range(len(self.comm_rates)), self.comm_rates)
        
        # Adjust limits
        for ax in [self.reward_plot.axes, self.queue_lines['J1'].axes, self.comm_plot.axes]:
            ax.relim()
            ax.autoscale_view()
        
        plt.draw()
        plt.pause(0.01)

