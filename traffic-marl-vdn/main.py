import os
import time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import json

from utils.sumo_env import SumoEnv
from agents.multi_agent_system import MultiAgentSystem

class Trainer:
    """Main training class for MARL traffic signal control"""
    
    def __init__(self, config_path: str = "configs/marl_config.json"):
        # Load configuration
        self.config = self.load_config(config_path)
        
        # Setup directories
        self.setup_directories()
        
        # Initialize environment
        print("Initializing SUMO environment...")
        self.env = SumoEnv(
            config_path=self.config['sumo_config_path'],
            use_gui=self.config.get('use_gui', False)
        )
        self.env.start()
        
        # Get traffic light IDs from environment
        self.agent_ids = self.env.tl_ids
        print(f"Agents: {self.agent_ids}")

        # Derive state dimension from environment's state vector
        initial_state = self.env.get_state()
        sample_agent = self.agent_ids[0]
        state_dim = int(initial_state[sample_agent].shape[0])

        # Initialize multi-agent system
        print("Initializing multi-agent system...")
        # SumoEnv supports 4 actions (0: extend, 1: NS green, 2: EW green, 3: emergency)
        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            state_dim=state_dim,
            action_dim=4,
            config=self.config['agent_config']
        )
        
        # Training metrics
        self.episode_rewards = []
        self.episode_lengths = []
        self.losses = []
        
    def load_config(self, config_path: str) -> dict:
        """Load training configuration"""
        default_config = {
            'sumo_config_path': 'sumo_configs/1x2.sumocfg',
            'use_gui': False,
            'num_episodes': 50,
            'max_steps_per_episode': 3600,
            'save_frequency': 10,
            'log_frequency': 1,
            
            'agent_config': {
                'learning_rate': 0.001,
                'gamma': 0.99,
                'epsilon_start': 1.0,
                'epsilon_min': 0.05,
                'epsilon_decay': 0.9995,
                'buffer_size': 10000,
                'central_buffer_size': 50000,
                'batch_size': 32,
                'target_update_freq': 10,
                'enable_communication': True
            }
        }
        
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                # Merge with default config
                default_config.update(user_config)
        
        return default_config
    
    def setup_directories(self):
        """Create necessary directories"""
        os.makedirs('models', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        os.makedirs('configs', exist_ok=True)
        
        # Save config for reference
        config_path = f"configs/config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def train_episode(self, episode: int) -> float:
        """Train for one episode"""
        state = self.env.reset()
        total_reward = 0
        episode_loss = 0
        step_count = 0
        
        for step in range(self.config['max_steps_per_episode']):
            # Get actions from all agents
            actions = self.multi_agent.act(state, training_mode=True)
            
            # Execute actions in environment
            next_state, reward, done, info = self.env.step(actions)
            
            # Store experience in centralized buffer
            # Convert states to array format
            state_array = np.array([state[agent_id] for agent_id in self.agent_ids])
            action_array = np.array([actions[agent_id] for agent_id in self.agent_ids])
            next_state_array = np.array([next_state[agent_id] for agent_id in self.agent_ids])
            
            experience = (state_array, action_array, reward, next_state_array, done)
            self.multi_agent.remember(experience)
            
            # Train the agents
            loss, grad_norm = self.multi_agent.train_step(
                batch_size=self.config['agent_config']['batch_size']
            )
            
            if loss > 0:
                episode_loss += loss
            
            # Update state
            state = next_state
            total_reward += reward
            step_count += 1
            
            # Log progress
            if step % 100 == 0:
                print(f"Episode {episode}, Step {step}: "
                    f"Reward={reward:.2f}, Loss={loss:.4f}")

            if done:
                break

         # After episode ends, decay epsilon
        for agent in self.multi_agent.agents.values():
            agent.epsilon = max(agent.epsilon_min, agent.epsilon * agent.epsilon_decay)
        
        return total_reward, episode_loss / max(step_count, 1), step_count
    
    def train(self):
        """Main training loop"""
        print(f"Starting training for {self.config['num_episodes']} episodes...")
        print("=" * 50)
        
        start_time = time.time()
        
        for episode in range(1, self.config['num_episodes'] + 1):
            # Train one episode
            episode_reward, avg_loss, episode_length = self.train_episode(episode)
            
            # Store metrics
            self.episode_rewards.append(episode_reward)
            self.episode_lengths.append(episode_length)
            self.losses.append(avg_loss)
            
            # Log episode results
            if episode % self.config['log_frequency'] == 0:
                print(f"\nEpisode {episode} Summary:")
                print(f"  Total Reward: {episode_reward:.2f}")
                print(f"  Avg Loss: {avg_loss:.4f}")
                print(f"  Episode Length: {episode_length}")
                print(f"  Epsilon: {self.multi_agent.agents[self.agent_ids[0]].epsilon:.3f}")
                print("-" * 30)
            
            # Save models periodically
            if episode % self.config['save_frequency'] == 0:
                model_dir = f"models/episode_{episode}"
                os.makedirs(model_dir, exist_ok=True)
                self.multi_agent.save_models(model_dir)
                print(f"Models saved to {model_dir}")
                
                # Save training progress
                self.save_training_progress(episode)
        
        # Training complete
        training_time = time.time() - start_time
        print(f"\nTraining completed in {training_time:.2f} seconds")
        
        # Save final models and plots
        self.save_final_results()
    
    def save_training_progress(self, episode: int):
        """Save training progress to file"""
        progress = {
            'episode': episode,
            'rewards': self.episode_rewards,
            'lengths': self.episode_lengths,
            'losses': self.losses,
            'timestamp': datetime.now().isoformat()
        }
        
        progress_path = f"logs/training_progress_ep{episode}.json"
        with open(progress_path, 'w') as f:
            json.dump(progress, f, indent=2)
    
    def save_final_results(self):
        """Save final models and create plots"""
        # Save final models
        final_dir = "models/final"
        os.makedirs(final_dir, exist_ok=True)
        self.multi_agent.save_models(final_dir)
        
        # Create and save plots
        self.plot_training_progress()
        
        # Save training summary
        summary = {
            'total_episodes': len(self.episode_rewards),
            'final_epsilon': self.multi_agent.agents[self.agent_ids[0]].epsilon,
            'avg_final_reward': np.mean(self.episode_rewards[-10:]) if len(self.episode_rewards) >= 10 else np.mean(self.episode_rewards),
            'config': self.config
        }
        
        summary_path = "logs/training_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
    
    def plot_training_progress(self):
        """Plot training metrics"""
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        
        # Episode rewards
        axes[0, 0].plot(self.episode_rewards)
        axes[0, 0].set_title('Episode Rewards')
        axes[0, 0].set_xlabel('Episode')
        axes[0, 0].set_ylabel('Total Reward')
        axes[0, 0].grid(True, alpha=0.3)
        
        # Moving average of rewards
        window = min(10, len(self.episode_rewards) // 10)
        if window > 0:
            moving_avg = np.convolve(self.episode_rewards, np.ones(window)/window, mode='valid')
            axes[0, 1].plot(moving_avg)
            axes[0, 1].set_title(f'Moving Average of Rewards (window={window})')
            axes[0, 1].set_xlabel('Episode')
            axes[0, 1].set_ylabel('Average Reward')
            axes[0, 1].grid(True, alpha=0.3)
        
        # Episode lengths
        axes[1, 0].plot(self.episode_lengths)
        axes[1, 0].set_title('Episode Lengths')
        axes[1, 0].set_xlabel('Episode')
        axes[1, 0].set_ylabel('Steps')
        axes[1, 0].grid(True, alpha=0.3)
        
        # Training loss
        if self.losses:
            axes[1, 1].plot(self.losses)
            axes[1, 1].set_title('Training Loss')
            axes[1, 1].set_xlabel('Episode')
            axes[1, 1].set_ylabel('Loss')
            axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plot_path = "logs/training_progress.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Training plots saved to {plot_path}")

def main():
    """Main function"""
    print("=" * 60)
    print("MARL Traffic Signal Control with VDN - Training")
    print("=" * 60)
    
    # Create trainer and start training
    trainer = Trainer()
    trainer.train()
    
    print("\nTraining complete!")
    print("Next steps:")
    print("1. Check 'models/final/' for trained models")
    print("2. Check 'logs/' for training statistics")
    print("3. Run evaluation script to test the trained models")

if __name__ == "__main__":
    main()