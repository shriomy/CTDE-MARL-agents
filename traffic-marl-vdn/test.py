import os
import time
import numpy as np
from utils.sumo_env import SumoEnv
from agents.multi_agent_system import MultiAgentSystem

class Evaluator:
    """Evaluate trained multi-agent system"""
    
    def __init__(self, model_path: str = "models/final"):
        # Initialize environment
        self.env = SumoEnv(
            config_path="sumo_configs/1x2.sumocfg",
            use_gui=True  # Show GUI for evaluation
        )
        self.env.start()
        
        # Get agent IDs
        self.agent_ids = self.env.tl_ids
        
        # Initialize multi-agent system
        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            state_dim=5,
            action_dim=2,
            config={'enable_communication': True}
        )
        
        # Load trained models
        if os.path.exists(model_path):
            self.multi_agent.load_models(model_path)
            print(f"Models loaded from {model_path}")
        else:
            print(f"Warning: Model path {model_path} not found")
    
    def evaluate_episode(self, render: bool = True):
        """Evaluate one episode"""
        state = self.env.reset()
        total_reward = 0
        step_count = 0
        done = False
        
        print("Starting evaluation episode...")
        
        while not done and step_count < 3600:
            # Get actions from agents (no exploration during evaluation)
            actions = self.multi_agent.act(state, training_mode=False)
            
            # Execute step
            next_state, reward, done, info = self.env.step(actions)
            
            # Update metrics
            total_reward += reward
            step_count += 1
            
            # Print progress
            if step_count % 100 == 0:
                print(f"Step {step_count}: Reward={reward:.2f}, "
                      f"Total={total_reward:.2f}, Vehicles={info['vehicle_count']}")
            
            # Update state
            state = next_state
        
        print(f"\nEvaluation completed:")
        print(f"  Total Steps: {step_count}")
        print(f"  Total Reward: {total_reward:.2f}")
        print(f"  Average Reward per Step: {total_reward/step_count:.4f}")
        
        return total_reward, step_count
    
    def compare_with_baseline(self, num_episodes: int = 5):
        """Compare MARL performance with fixed-time baseline"""
        print("\n" + "=" * 60)
        print("Performance Comparison: MARL vs Fixed-Time Control")
        print("=" * 60)
        
        marl_rewards = []
        baseline_rewards = []
        
        for episode in range(num_episodes):
            print(f"\nEpisode {episode + 1}/{num_episodes}")
            
            # Test MARL
            marl_reward, _ = self.evaluate_episode(render=False)
            marl_rewards.append(marl_reward)
            
            # Test baseline (fixed-time)
            baseline_reward = self.test_fixed_time_baseline()
            baseline_rewards.append(baseline_reward)
            
            print(f"MARL Reward: {marl_reward:.2f}, "
                  f"Baseline Reward: {baseline_reward:.2f}")
        
        # Calculate statistics
        avg_marl = np.mean(marl_rewards)
        avg_baseline = np.mean(baseline_rewards)
        improvement = ((avg_marl - avg_baseline) / abs(avg_baseline)) * 100
        
        print("\n" + "=" * 60)
        print("Comparison Results:")
        print(f"Average MARL Reward: {avg_marl:.2f}")
        print(f"Average Baseline Reward: {avg_baseline:.2f}")
        print(f"Improvement: {improvement:.2f}%")
        
        if improvement > 0:
            print("✅ MARL outperforms fixed-time control!")
        else:
            print("❌ MARL needs more training")
        
        return marl_rewards, baseline_rewards
    
    def test_fixed_time_baseline(self) -> float:
        """Test fixed-time traffic light control (baseline)"""
        self.env.reset()
        total_reward = 0
        step_count = 0
        
        # Fixed-time control: switch phases every 30 seconds
        while step_count < 3600:
            actions = {}
            for tl_id in self.agent_ids:
                # Switch phase every 30 seconds
                if step_count % 30 == 0:
                    actions[tl_id] = 1  # Switch phase
                else:
                    actions[tl_id] = 0  # Keep phase
            
            _, reward, done, _ = self.env.step(actions)
            total_reward += reward
            step_count += 1
            
            if done:
                break
        
        return total_reward

def main():
    """Main evaluation function"""
    print("=" * 60)
    print("MARL Traffic Signal Control - Evaluation")
    print("=" * 60)
    
    # Initialize evaluator
    evaluator = Evaluator()
    
    # Run single evaluation
    print("\nRunning single evaluation episode...")
    evaluator.evaluate_episode(render=True)
    
    # Run comparison with baseline
    run_comparison = input("\nRun comparison with baseline? (y/n): ")
    if run_comparison.lower() == 'y':
        evaluator.compare_with_baseline(num_episodes=3)
    
    print("\nEvaluation complete!")

if __name__ == "__main__":
    main()