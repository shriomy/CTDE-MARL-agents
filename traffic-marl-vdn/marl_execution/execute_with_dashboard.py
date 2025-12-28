"""
Enhanced executor with WebSocket dashboard integration.
This combines the executor with real-time dashboard updates.
"""
import sys
import os
sys.path.append('..')

from executor import MARLExecutor
from lightweight_server import LightweightDashboardServer
import time
import numpy as np

class DashboardMARLExecutor(MARLExecutor):
    """MARL executor with real-time dashboard updates"""
    
    def __init__(self, config_path: str = "../configs/marl_config.json"):
        super().__init__(config_path)
        
        # Initialize WebSocket server
        print("\nInitializing WebSocket server for dashboard...")
        self.dashboard_server = LightweightDashboardServer()
        self.dashboard_server.start_server()
        
        # Give server time to start
        time.sleep(2)
        
        # Send initial system status
        self.dashboard_server.send_system_status(
            "initialized", 
            f"Controlling {len(self.agent_ids)} agents"
        )
    
    def execute_episode(self, episode_num: int = 1, max_steps: int = 1800):
        """Execute episode with dashboard updates"""
        print(f"\n{'='*60}")
        print(f"Starting Execution Episode {episode_num} (with Dashboard)")
        print(f"{'='*60}")
        
        # Notify dashboard
        self.dashboard_server.send_system_status(
            "episode_start",
            f"Starting episode {episode_num}"
        )
        
        state = self.env.reset()
        total_reward = 0
        step_metrics = []
        
        for step in range(max_steps):
            # Get actions with coordination
            actions = self.multi_agent.act_with_coordination(
                state, 
                training_mode=False
            )
            
            # Send agent decisions to dashboard
            for agent_id, action in actions.items():
                self.dashboard_server.send_agent_decision(
                    agent_id, 
                    action, 
                    {
                        "queue_lengths": (state[agent_id][:4] * 10.0).tolist(),
                        "waiting_times": (state[agent_id][4:8] * 60.0).tolist(),
                        "current_green": int(np.argmax(state[agent_id][8:12]))
                    }
                )
            
            # Execute in SUMO
            next_state, reward, done, info = self.env.step(actions)
            
            # Prepare step data for dashboard
            step_data = {
                'step': step,
                'reward': reward,
                'total_reward': total_reward + reward,
                'actions': {agent_id: actions[agent_id] for agent_id in self.agent_ids},
                'vehicle_count': info['vehicle_count'],
                'avg_speed': info['avg_speed'],
                'timestamp': time.time()
            }
            
            # Add queue information for each agent
            for agent_id in self.agent_ids:
                agent_state = state[agent_id]
                step_data[f'{agent_id}_queues'] = (agent_state[:4] * 10.0).tolist()
                step_data[f'{agent_id}_waits'] = (agent_state[4:8] * 60.0).tolist()
            
            # Send to dashboard
            self.dashboard_server.send_traffic_update(step_data)
            
            # Update metrics
            step_metrics.append(step_data)
            total_reward += reward
            state = next_state
            
            # Log to console every 100 steps
            if step % 100 == 0:
                print(f"Step {step}: Reward={reward:.2f}, "
                      f"Vehicles={info['vehicle_count']}, "
                      f"Speed={info['avg_speed']:.1f} m/s")
            
            if done:
                self.dashboard_server.send_system_status(
                    "episode_end",
                    f"Episode {episode_num} ended at step {step}"
                )
                break
        
        # Send episode summary to dashboard
        self.dashboard_server.send_system_status(
            "episode_complete",
            f"Episode {episode_num} completed: {len(step_metrics)} steps, "
            f"Total reward: {total_reward:.2f}"
        )
        
        # Save metrics
        self.save_episode_metrics(step_metrics, episode_num)
        
        return total_reward, step_metrics

def main():
    """Main function for execution with dashboard"""
    print("="*60)
    print("MARL Traffic Control - EXECUTION WITH DASHBOARD")
    print("="*60)
    
    print("\nInstructions:")
    print("1. Open a web browser to http://localhost:3000 (React dashboard)")
    print("2. WebSocket server runs on ws://localhost:8765")
    print("3. Watch SUMO GUI for traffic visualization")
    print("4. Check logs/execution/ for detailed metrics")
    
    # Initialize enhanced executor
    executor = DashboardMARLExecutor()
    
    # Run execution
    try:
        executor.run(num_episodes=1)
    except KeyboardInterrupt:
        print("\nExecution interrupted by user")
    finally:
        # Cleanup
        executor.dashboard_server.send_system_status("shutdown", "Execution stopped")
        executor.env.close()
        print("\nExecution stopped. Dashboard may still be running.")

if __name__ == "__main__":
    main()