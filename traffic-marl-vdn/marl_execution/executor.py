# Save this as marl_execution/executor_fixed.py
import os
import sys
import time
import json
import numpy as np
from datetime import datetime

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, ".."))

try:
    from utils.sumo_env_new import SumoEnv
    from agents.multi_agent_system import MultiAgentSystem
    print("✓ Successfully imported all modules")
except ImportError as e:
    print(f"✗ Import error: {e}")
    print(f"Python path: {sys.path}")
    sys.exit(1)

class MARLExecutor:
    """Decentralized execution of trained MARL agents"""
    
    def __init__(self):
        # Configuration - using absolute paths
        self.config = {
            'sumo_config_path': os.path.join(project_root, "..", "sumo_configs", "1x2.sumocfg"),
            'use_gui': True,
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
                'enable_communication': True,
                'num_actions': 5
            }
        }
        
        # Verify SUMO config exists
        print(f"SUMO config: {self.config['sumo_config_path']}")
        if not os.path.exists(self.config['sumo_config_path']):
            print("✗ ERROR: SUMO config file not found!")
            print(f"Looking for: {self.config['sumo_config_path']}")
            sys.exit(1)
        print("✓ SUMO config file found")
        
        # Initialize SUMO environment
        print("Starting SUMO environment...")
        self.env = SumoEnv(
            config_path=self.config['sumo_config_path'],
            use_gui=True
        )
        self.env.start()
        print("✓ SUMO started successfully")
        
        # Get traffic light IDs
        self.agent_ids = self.env.tl_ids
        print(f"Agents to control: {self.agent_ids}")
        
        # Get state dimension
        initial_state = self.env.get_state()
        sample_agent = self.agent_ids[0]
        base_state_dim = int(initial_state[sample_agent].shape[0])  # Should be 13
        enhanced_state_dim = base_state_dim + 10  # 13 + 10 = 23
        print(f"State dimensions: base={base_state_dim}, enhanced={enhanced_state_dim}")
        
        # Initialize multi-agent system
        print("Initializing multi-agent system...")
        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            state_dim=enhanced_state_dim,
            action_dim=5,
            config=self.config['agent_config']
        )
        
        # Load trained models
        print("Looking for trained models...")
        model_dirs = [
            os.path.join(project_root, "..", "models", "final"),
            os.path.join(project_root, "..", "models", "episode_100"),
            os.path.join(project_root, "..", "models", "episode_50"),
            os.path.join(project_root, "..", "models", "episode_10"),
        ]
        
        loaded = False
        for model_dir in model_dirs:
            if os.path.exists(model_dir):
                print(f"  Trying: {model_dir}")
                if self.multi_agent.load_models(model_dir):
                    print(f"✓ Models loaded from {model_dir}")
                    loaded = True
                    break
        
        if not loaded:
            print("✗ WARNING: No trained models found!")
            print("  The agents will use random policies")
            print("  Make sure to train models first with: python main.py")
        
        # Disable exploration
        for agent_id in self.agent_ids:
            self.multi_agent.agents[agent_id].epsilon = 0.0
            print(f"  {agent_id}: epsilon = {self.multi_agent.agents[agent_id].epsilon}")
        
        # Enable communication
        self.multi_agent.communication_enabled = True
        print("Communication enabled: Yes")
        
        # Create logs directory
        log_dir = os.path.join(project_root, "..", "logs", "execution")
        os.makedirs(log_dir, exist_ok=True)
        print(f"Logs will be saved to: {log_dir}")
        
        # Metrics
        self.metrics = {
            'step': 0,
            'total_reward': 0,
            'queue_history': [],
            'action_history': [],
            'reward_history': []
        }
        
        print("\n" + "="*60)
        print("READY FOR DECENTRALIZED EXECUTION")
        print("="*60)
    
    def run_single_episode(self, max_steps=None):
        """Run continuous decentralized execution"""
        print(f"\nStarting continuous execution")
        print("Press Ctrl+C in this terminal to stop")
        print("-" * 40)
        
        # Reset environment
        state = self.env.reset()
        
        step = 0
        try:
            while True:  # Run forever until interrupted
                # Get actions from agents
                actions = self.multi_agent.act_with_coordination(
                    state, 
                    training_mode=False
                )
                
                # Execute in SUMO
                next_state, reward, done, info = self.env.step(actions)
                
                # Print progress every 50 steps
                if step % 50 == 0:
                    print(f"\nStep {step}:")
                    print(f"  Reward: {reward:.2f}")
                    print(f"  Vehicles: {info['vehicle_count']}, Speed: {info['avg_speed']:.1f} m/s")
                    
                    for agent_id in self.agent_ids:
                        queues = state[agent_id][:4] * 10.0
                        action_names = ["WEST", "NORTH", "EAST", "SOUTH", "EXTEND"]
                        print(f"  {agent_id}:")
                        print(f"    Action: {action_names[actions[agent_id]]}")
                        print(f"    Queues: W={queues[0]:.1f}, N={queues[1]:.1f}, "
                            f"E={queues[2]:.1f}, S={queues[3]:.1f}")
                
                # Update state
                state = next_state
                step += 1
                
                # Check if SUMO simulation ended (reached 3600 seconds)
                if done:
                    print(f"\nSUMO simulation reached time limit (3600 seconds)")
                    print("Resetting simulation...")
                    state = self.env.reset()
                    step = 0
                
                # Small delay to make it watchable
                time.sleep(0.05)
                
        except KeyboardInterrupt:
            print("\n\nExecution stopped by user")
            self.save_metrics()
    
    def save_metrics(self):
        """Save execution metrics to file"""
        import json
        from datetime import datetime
        
        log_dir = os.path.join(project_root, "..", "logs", "execution")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save detailed metrics
        metrics_file = os.path.join(log_dir, f"execution_{timestamp}.json")
        with open(metrics_file, 'w') as f:
            json.dump(self.metrics, f, indent=2)
        
        # Save summary
        summary = {
            'timestamp': timestamp,
            'total_steps': self.metrics['step'],
            'total_reward': float(self.metrics['total_reward']),
            'avg_reward': float(np.mean(self.metrics['reward_history'])) if self.metrics['reward_history'] else 0,
            'agents': self.agent_ids,
            'final_queues': self.metrics['queue_history'][-1] if self.metrics['queue_history'] else {}
        }
        
        summary_file = os.path.join(log_dir, f"summary_{timestamp}.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\nMetrics saved to: {metrics_file}")
        print(f"Summary saved to: {summary_file}")
        
        # Print action statistics
        print("\nAction Statistics:")
        for agent_id in self.agent_ids:
            actions = [step[agent_id] for step in self.metrics['action_history'] if agent_id in step]
            if actions:
                unique, counts = np.unique(actions, return_counts=True)
                action_names = ["WEST", "NORTH", "EAST", "SOUTH", "EXTEND"]
                print(f"  {agent_id}:")
                for action, count in zip(unique, counts):
                    percentage = (count / len(actions)) * 100
                    print(f"    {action_names[action]}: {count} times ({percentage:.1f}%)")
    
    def run(self):
        """Main execution loop"""
        self.run_single_episode(max_steps=500)
        
        # Close SUMO
        self.env.close()
        print("\nSUMO closed. Execution complete!")

def main():
    print("="*60)
    print("MARL TRAFFIC CONTROL - DECENTRALIZED EXECUTION")
    print("="*60)
    print("This will:")
    print("1. Start SUMO GUI with your 1x2 network")
    print("2. Load trained MARL agents")
    print("3. Execute decentralized control with coordination")
    print("4. Log all actions and metrics")
    print("="*60)
    
    input("Press Enter to start (or Ctrl+C to cancel)...")
    
    executor = MARLExecutor()
    executor.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecution cancelled by user")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()