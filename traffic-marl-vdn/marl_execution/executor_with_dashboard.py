"""
Enhanced executor with complete WebSocket dashboard integration.
"""
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
    # Try to import dashboard server, but it's optional
    try:
        from dashboard_server import SimpleDashboardServer
        DASHBOARD_AVAILABLE = True
    except ImportError:
        print("⚠ Dashboard server not available, running without dashboard")
        DASHBOARD_AVAILABLE = False
    print("✓ Successfully imported all modules")
except ImportError as e:
    print(f"✗ Import error: {e}")
    print(f"Python path: {sys.path}")
    sys.exit(1)

class DashboardMARLExecutor:
    """MARL executor with real-time dashboard updates"""
    
    def __init__(self):
        # Configuration
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
        
        # Verify SUMO config
        if not os.path.exists(self.config['sumo_config_path']):
            print(f"✗ ERROR: SUMO config not found at {self.config['sumo_config_path']}")
            sys.exit(1)
        
        # Initialize dashboard server (if available)
        self.dashboard = None
        if DASHBOARD_AVAILABLE:
            print("\nStarting WebSocket Dashboard Server...")
            try:
                self.dashboard = SimpleDashboardServer(host="localhost", port=8765)
                self.dashboard.start()
                time.sleep(1)  # Give server time to start
                print("✓ WebSocket server started on ws://localhost:8765")
            except Exception as e:
                print(f"⚠ Failed to start dashboard server: {e}")
                print("Continuing without dashboard...")
                self.dashboard = None
        else:
            print("⚠ Running without dashboard server")
        
        # Initialize SUMO
        print("Starting SUMO environment...")
        self.env = SumoEnv(
            config_path=self.config['sumo_config_path'],
            use_gui=True
        )
        self.env.start()
        
        # Get agents
        self.agent_ids = self.env.tl_ids
        print(f"✓ Controlling agents: {self.agent_ids}")
        
        # Initialize multi-agent system
        initial_state = self.env.get_state()
        sample_agent = self.agent_ids[0]
        base_state_dim = int(initial_state[sample_agent].shape[0])
        enhanced_state_dim = base_state_dim + 10
        
        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            state_dim=enhanced_state_dim,
            action_dim=5,
            config=self.config['agent_config']
        )
        
        # Load trained models
        self.load_models()
        
        # Disable exploration
        for agent_id in self.agent_ids:
            self.multi_agent.agents[agent_id].epsilon = 0.0
        
        # Enable communication
        self.multi_agent.communication_enabled = True
        
        # Metrics
        self.metrics = {
            'step': 0,
            'total_reward': 0,
            'queue_history': [],
            'action_history': [],
            'reward_history': [],
            'vehicle_history': [],
            'speed_history': []
        }
        
        # Action names for display
        self.action_names = ["WEST", "NORTH", "EAST", "SOUTH", "EXTEND"]
        
        # Notify dashboard if available
        if self.dashboard:
            self.dashboard.send_system_status(
                "ready",
                f"System ready with {len(self.agent_ids)} agents"
            )
        
        print("\n" + "="*60)
        print("MARL EXECUTOR READY")
        print("="*60)
        if self.dashboard:
            print("Dashboard WebSocket: ws://localhost:8765")
            print("Open simple_dashboard.html in your browser")
        else:
            print("Running without dashboard (console output only)")
        print("="*60)
    
    def load_models(self):
        """Load trained models"""
        print("Loading trained models...")
        model_dirs = [
            os.path.join(project_root, "..", "models", "final"),
            os.path.join(project_root, "..", "models", "episode_100"),
            os.path.join(project_root, "..", "models", "episode_50"),
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
            print("⚠ WARNING: No trained models found, using random policies")
    
    def prepare_dashboard_data(self, step: int, state: dict, actions: dict, reward: float, info: dict) -> dict:
        """Prepare data for dashboard"""
        step_data = {
            'step': step,
            'reward': float(reward),
            'total_reward': float(self.metrics['total_reward']),
            'vehicle_count': info['vehicle_count'],
            'avg_speed': float(info['avg_speed']),
            'timestamp': time.time(),
            'agents': {}
        }
        
        # Add agent-specific data
        for agent_id in self.agent_ids:
            agent_state = state[agent_id]
            step_data['agents'][agent_id] = {
                'action': int(actions[agent_id]),
                'action_name': self.action_names[actions[agent_id]],
                'queues': (agent_state[:4] * 10.0).tolist(),  # [W, N, E, S]
                'waits': (agent_state[4:8] * 60.0).tolist()   # [W, N, E, S]
            }
        
        return step_data
    
    def send_to_dashboard(self, step_data: dict):
        """Send data to dashboard if available"""
        if self.dashboard:
            try:
                self.dashboard.send_traffic_update(step_data)
            except Exception as e:
                print(f"⚠ Dashboard error: {e}")
    
    def run_execution(self):
        """Main execution loop with dashboard updates"""
        print("\nStarting decentralized execution...")
        print("Press Ctrl+C to stop\n")
        
        # Notify dashboard
        if self.dashboard:
            self.dashboard.send_system_status("executing", "Starting execution")
        
        # Reset environment
        state = self.env.reset()
        
        step = 0
        try:
            while True:
                # Get actions from agents
                actions = self.multi_agent.act_with_coordination(
                    state, 
                    training_mode=False
                )
                
                # Execute in SUMO
                next_state, reward, done, info = self.env.step(actions)
                
                # Update metrics
                self.metrics['step'] = step
                self.metrics['total_reward'] += reward
                self.metrics['reward_history'].append(reward)
                self.metrics['vehicle_history'].append(info['vehicle_count'])
                self.metrics['speed_history'].append(info['avg_speed'])
                
                # Prepare and send data to dashboard
                step_data = self.prepare_dashboard_data(step, state, actions, reward, info)
                self.send_to_dashboard(step_data)
                
                # Console output every 100 steps
                if step % 100 == 0:
                    print(f"Step {step}: Reward={reward:.2f}, "
                          f"Total={self.metrics['total_reward']:.2f}, "
                          f"Vehicles={info['vehicle_count']}, "
                          f"Speed={info['avg_speed']:.1f} m/s")
                    
                    # Show agent actions
                    for agent_id in self.agent_ids:
                        action = actions[agent_id]
                        queues = state[agent_id][:4] * 10.0
                        print(f"  {agent_id}: {self.action_names[action]} | "
                              f"Queues: W={queues[0]:.1f}, N={queues[1]:.1f}, "
                              f"E={queues[2]:.1f}, S={queues[3]:.1f}")
                
                # Update state
                state = next_state
                step += 1
                
                # Check if simulation ended
                if done:
                    print(f"\nSUMO simulation reached time limit, resetting...")
                    if self.dashboard:
                        self.dashboard.send_system_status("resetting", "Simulation resetting")
                    state = self.env.reset()
                    step = 0
                    if self.dashboard:
                        self.dashboard.send_system_status("executing", "Simulation restarted")
                
                # Small delay for visualization
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n\nExecution stopped by user")
            if self.dashboard:
                self.dashboard.send_system_status("stopped", "Execution stopped by user")
        except Exception as e:
            print(f"\nERROR during execution: {e}")
            import traceback
            traceback.print_exc()
            if self.dashboard:
                self.dashboard.send_system_status("error", f"Execution error: {str(e)}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        print("\nCleaning up...")
        
        # Save metrics
        self.save_metrics()
        
        # Close SUMO
        self.env.close()
        
        # Final dashboard update
        if self.dashboard:
            self.dashboard.send_system_status(
                "shutdown", 
                f"Execution complete. Total steps: {self.metrics['step']}, "
                f"Total reward: {self.metrics['total_reward']:.2f}"
            )
        
        print("\n✓ Cleanup complete")
    
    def save_metrics(self):
        """Save execution metrics"""
        import json
        from datetime import datetime
        
        log_dir = os.path.join(project_root, "..", "logs", "execution")
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save detailed metrics
        metrics_file = os.path.join(log_dir, f"execution_{timestamp}.json")
        with open(metrics_file, 'w') as f:
            json.dump(self.metrics, f, indent=2, default=float)
        
        # Create summary
        summary = {
            'timestamp': timestamp,
            'total_steps': self.metrics['step'],
            'total_reward': float(self.metrics['total_reward']),
            'avg_reward': float(np.mean(self.metrics['reward_history'])) if self.metrics['reward_history'] else 0,
            'max_vehicles': int(max(self.metrics['vehicle_history'])) if self.metrics['vehicle_history'] else 0,
            'avg_speed': float(np.mean(self.metrics['speed_history'])) if self.metrics['speed_history'] else 0,
            'agents': self.agent_ids,
        }
        
        summary_file = os.path.join(log_dir, f"summary_{timestamp}.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n✓ Metrics saved to: {metrics_file}")
        print(f"✓ Summary saved to: {summary_file}")
        
        # Print action statistics
        print("\nAction Statistics (last 500 steps):")
        recent_steps = min(500, self.metrics['step'])
        if recent_steps > 0:
            for agent_id in self.agent_ids:
                # Get actions from recent steps (you'll need to track this)
                print(f"  {agent_id}: Actions tracked in logs")
    
    def run(self):
        """Main entry point"""
        print("="*60)
        print("MARL TRAFFIC CONTROL - EXECUTION")
        print("="*60)
        
        self.run_execution()

def main():
    """Main function"""
    try:
        executor = DashboardMARLExecutor()
        executor.run()
    except KeyboardInterrupt:
        print("\n\nExecution cancelled by user")
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()