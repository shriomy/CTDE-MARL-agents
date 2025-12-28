"""
MARL Executor with real-time dashboard integration
"""
import os
import sys
import time
import json
import numpy as np
from datetime import datetime
from typing import Dict, Any

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, ".."))

from utils.sumo_env_new import SumoEnv
from agents.multi_agent_system import MultiAgentSystem
from dashboard_server import DashboardServer

class DashboardMARLExecutor:
    """MARL executor with real-time dashboard updates"""
    
    def __init__(self):
        self.config = {
            'sumo_config_path': os.path.join(project_root, "..", "sumo_configs", "1x2.sumocfg"),
            'use_gui': True,
            'agent_config': {
                'enable_communication': True,
                'num_actions': 5
            }
        }
        
        print("="*70)
        print("MARL TRAFFIC CONTROL WITH REAL-TIME DASHBOARD")
        print("="*70)
        
        # Start WebSocket server first
        print("\n1. Starting WebSocket server for dashboard...")
        self.dashboard = DashboardServer(host="localhost", port=8765)
        self.dashboard.start()
        
        # Start SUMO environment
        print("\n2. Starting SUMO environment...")
        self.env = SumoEnv(
            config_path=self.config['sumo_config_path'],
            use_gui=True
        )
        self.env.start()
        
        # Get agents
        self.agent_ids = self.env.tl_ids
        print(f"   Agents: {self.agent_ids}")
        
        # Initialize multi-agent system
        print("\n3. Initializing multi-agent system...")
        initial_state = self.env.get_state()
        base_state_dim = initial_state[self.agent_ids[0]].shape[0]
        enhanced_state_dim = base_state_dim + 10
        
        self.multi_agent = MultiAgentSystem(
            agent_ids=self.agent_ids,
            state_dim=enhanced_state_dim,
            action_dim=5,
            config=self.config['agent_config']
        )
        
        # Load trained models
        print("\n4. Loading trained models...")
        self.load_models()
        
        # Disable exploration
        for agent_id in self.agent_ids:
            self.multi_agent.agents[agent_id].epsilon = 0.0
        
        # Action names for display
        self.action_names = ["WEST", "NORTH", "EAST", "SOUTH", "EXTEND"]
        self.action_colors = {
            0: "#FF6B6B",  # West - Red
            1: "#4ECDC4",  # North - Teal
            2: "#FFD166",  # East - Yellow
            3: "#06D6A0",  # South - Green
            4: "#118AB2"   # Extend - Blue
        }
        
        # Metrics tracking
        self.metrics = {
            'total_steps': 0,
            'total_reward': 0,
            'step_rewards': [],
            'queue_history': {agent_id: [] for agent_id in self.agent_ids},
            'wait_history': {agent_id: [] for agent_id in self.agent_ids},
            'action_history': {agent_id: [] for agent_id in self.agent_ids},
            'communication_events': []
        }
        
        # Send initial dashboard data
        self.dashboard.send_system_status_update(
            "initialized", 
            f"System ready. Controlling {len(self.agent_ids)} agents"
        )
        
        print("\n" + "="*70)
        print("✅ SYSTEM READY")
        print("="*70)
        print("Dashboard: http://localhost:3000 (or open dashboard.html)")
        print("WebSocket: ws://localhost:8765")
        print("\nPress Ctrl+C to stop execution")
        print("="*70)
    
    def load_models(self):
        """Load trained models"""
        model_dirs = [
            os.path.join(project_root, "..", "models", "final"),
            os.path.join(project_root, "..", "models", "episode_100"),
            os.path.join(project_root, "..", "models", "episode_50"),
        ]
        
        for model_dir in model_dirs:
            if os.path.exists(model_dir):
                print(f"   Trying: {model_dir}")
                if self.multi_agent.load_models(model_dir):
                    print(f"   ✓ Models loaded from {model_dir}")
                    return
        
        print("   ⚠ No trained models found. Using random policy.")
        for agent_id in self.agent_ids:
            self.multi_agent.agents[agent_id].epsilon = 1.0
    
    def run(self):
        """Main execution loop with dashboard updates"""
        state = self.env.reset()
        
        try:
            while True:
                # Get coordinated actions
                actions = self.multi_agent.act_with_coordination(state, training_mode=False)
                
                # Execute in SUMO
                next_state, reward, done, info = self.env.step(actions)
                
                # Update metrics
                self.metrics['total_steps'] += 1
                self.metrics['total_reward'] += reward
                self.metrics['step_rewards'].append(reward)
                
                # Prepare dashboard data
                dashboard_data = self.prepare_dashboard_data(state, actions, reward, info)
                
                # Send to dashboard
                self.dashboard.send_traffic_update(dashboard_data)
                
                # Send individual agent decisions with reasoning
                for agent_id in self.agent_ids:
                    self.send_agent_decision_data(agent_id, state[agent_id], actions[agent_id])
                
                # Store detailed metrics
                self.store_detailed_metrics(state, actions)
                
                # Display console output every 50 steps
                if self.metrics['total_steps'] % 50 == 0:
                    self.display_console_update(state, actions, reward, info)
                
                # Send periodic metric updates to dashboard
                if self.metrics['total_steps'] % 20 == 0:
                    self.send_performance_metrics()
                
                # Check if simulation ended
                if done:
                    print("\n🔄 SUMO simulation resetting...")
                    state = self.env.reset()
                    self.dashboard.send_system_status_update("resetting", "SUMO simulation resetting")
                else:
                    state = next_state
                
                # Small delay for smooth visualization
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n\n" + "="*70)
            print("EXECUTION STOPPED BY USER")
            print("="*70)
            self.save_final_metrics()
        finally:
            self.cleanup()
    
    def prepare_dashboard_data(self, state, actions, reward, info) -> Dict[str, Any]:
        """Prepare data for dashboard update"""
        step_data = {
            'step': self.metrics['total_steps'],
            'timestamp': time.time(),
            'reward': float(reward),
            'total_reward': float(self.metrics['total_reward']),
            'vehicles': info.get('vehicle_count', 0),
            'avg_speed': float(info.get('avg_speed', 0)),
            'agents': {},
            'communication': []
        }
        
        # Add agent-specific data
        for agent_id in self.agent_ids:
            agent_state = state[agent_id]
            queues = (agent_state[:4] * 10.0).tolist()  # De-normalize
            waits = (agent_state[4:8] * 60.0).tolist()  # De-normalize
            
            # Determine current green direction
            green_vector = agent_state[8:12]
            current_green = np.argmax(green_vector) if np.any(green_vector) else -1
            
            step_data['agents'][agent_id] = {
                'queues': queues,
                'waits': waits,
                'current_green': int(current_green),
                'action': int(actions[agent_id]),
                'action_name': self.action_names[actions[agent_id]],
                'action_color': self.action_colors[actions[agent_id]],
                'phase_duration': float(agent_state[12] * 60.0)  # De-normalize
            }
            
            # Store for metrics
            self.metrics['queue_history'][agent_id].append(np.mean(queues))
            self.metrics['wait_history'][agent_id].append(np.mean(waits))
            self.metrics['action_history'][agent_id].append(actions[agent_id])
        
        return step_data
    
    def send_agent_decision_data(self, agent_id, agent_state, action):
        """Send detailed agent decision data to dashboard"""
        queues = agent_state[:4] * 10.0
        max_queue_idx = np.argmax(queues)
        max_queue_val = queues[max_queue_idx]
        
        # Simple reasoning based on queues
        reasoning = ""
        if action == 4:  # EXTEND
            reasoning = "Extending current green phase"
        elif action == max_queue_idx:
            reasoning = f"Switching to {self.action_names[action]} (highest queue: {max_queue_val:.1f} vehicles)"
        else:
            reasoning = f"Choosing {self.action_names[action]} (coordination with neighbors)"
        
        self.dashboard.send_agent_decision(
            agent_id=agent_id,
            action=action,
            state={
                'queues': queues.tolist(),
                'waits': (agent_state[4:8] * 60.0).tolist(),
                'current_green': int(np.argmax(agent_state[8:12]) if np.any(agent_state[8:12]) else -1)
            },
            reasoning=reasoning
        )
    
    def store_detailed_metrics(self, state, actions):
        """Store detailed metrics for analysis"""
        # This can be expanded to store more detailed metrics
        pass
    
    def display_console_update(self, state, actions, reward, info):
        """Display update in console"""
        print(f"\n📊 STEP {self.metrics['total_steps']}")
        print(f"   Reward: {reward:.2f} (Total: {self.metrics['total_reward']:.2f})")
        print(f"   Vehicles: {info.get('vehicle_count', 0)}, Speed: {info.get('avg_speed', 0):.1f} m/s")
        
        for agent_id in self.agent_ids:
            queues = state[agent_id][:4] * 10.0
            action = actions[agent_id]
            print(f"   {agent_id}: {self.action_names[action]}")
            print(f"        Queues: W={queues[0]:.1f}, N={queues[1]:.1f}, "
                  f"E={queues[2]:.1f}, S={queues[3]:.1f}")
    
    def send_performance_metrics(self):
        """Send performance metrics to dashboard"""
        if self.metrics['total_steps'] > 0:
            metrics = {
                'steps': self.metrics['total_steps'],
                'avg_reward': float(np.mean(self.metrics['step_rewards'][-100:]) if self.metrics['step_rewards'] else 0),
                'avg_queue': {agent_id: float(np.mean(self.metrics['queue_history'][agent_id][-50:])) if self.metrics['queue_history'][agent_id] else 0 
                            for agent_id in self.agent_ids},
                'avg_wait': {agent_id: float(np.mean(self.metrics['wait_history'][agent_id][-50:])) if self.metrics['wait_history'][agent_id] else 0
                           for agent_id in self.agent_ids},
                'action_distribution': {
                    agent_id: {
                        action: self.metrics['action_history'][agent_id].count(action)
                        for action in range(5)
                    }
                    for agent_id in self.agent_ids
                }
            }
            
            self.dashboard.send_metric_update(metrics)
    
    def save_final_metrics(self):
        """Save final metrics to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(project_root, "..", "logs", "dashboard")
        os.makedirs(log_dir, exist_ok=True)
        
        # Prepare final metrics
        final_metrics = {
            'execution_summary': {
                'total_steps': self.metrics['total_steps'],
                'total_reward': float(self.metrics['total_reward']),
                'avg_reward_per_step': float(self.metrics['total_reward'] / max(1, self.metrics['total_steps'])),
                'start_time': self.metrics.get('start_time', time.time()),
                'end_time': time.time(),
                'duration': time.time() - self.metrics.get('start_time', time.time())
            },
            'agent_performance': {},
            'action_statistics': {}
        }
        
        # Calculate agent performance
        for agent_id in self.agent_ids:
            # Queue statistics
            queues = self.metrics['queue_history'][agent_id]
            waits = self.metrics['wait_history'][agent_id]
            actions = self.metrics['action_history'][agent_id]
            
            final_metrics['agent_performance'][agent_id] = {
                'avg_queue': float(np.mean(queues)) if queues else 0,
                'max_queue': float(np.max(queues)) if queues else 0,
                'avg_wait': float(np.mean(waits)) if waits else 0,
                'total_actions': len(actions)
            }
            
            # Action distribution
            action_counts = {action: actions.count(action) for action in range(5)}
            total_actions = len(actions)
            
            final_metrics['action_statistics'][agent_id] = {
                self.action_names[action]: {
                    'count': count,
                    'percentage': (count / total_actions * 100) if total_actions > 0 else 0
                }
                for action, count in action_counts.items()
            }
        
        # Save to file
        metrics_file = os.path.join(log_dir, f"dashboard_metrics_{timestamp}.json")
        with open(metrics_file, 'w') as f:
            json.dump(final_metrics, f, indent=2)
        
        print(f"\n📁 Metrics saved to: {metrics_file}")  # FIXED THIS LINE
        
        # Print summary
        print("\n" + "="*70)
        print("EXECUTION SUMMARY")
        print("="*70)
        print(f"Total Steps: {final_metrics['execution_summary']['total_steps']}")
        print(f"Total Reward: {final_metrics['execution_summary']['total_reward']:.2f}")
        print(f"Duration: {final_metrics['execution_summary']['duration']:.1f} seconds")
        
        print("\nAgent Performance:")
        for agent_id, perf in final_metrics['agent_performance'].items():
            print(f"  {agent_id}:")
            print(f"    Avg Queue: {perf['avg_queue']:.1f} vehicles")
            print(f"    Avg Wait: {perf['avg_wait']:.1f} seconds")
        
        print("\nAction Distribution:")
        for agent_id, stats in final_metrics['action_statistics'].items():
            print(f"  {agent_id}:")
            for action_name, data in stats.items():
                if data['percentage'] > 0:
                    print(f"    {action_name}: {data['count']} ({data['percentage']:.1f}%)")
    
    def cleanup(self):
        """Cleanup resources"""
        print("\n🧹 Cleaning up...")
        
        # Send final status to dashboard
        self.dashboard.send_system_status_update(
            "shutting_down", 
            f"Execution complete. Total steps: {self.metrics['total_steps']}"
        )
        
        # Close SUMO
        self.env.close()
        print("✅ SUMO closed")
        
        # Save final metrics
        self.save_final_metrics()
        
        print("\n" + "="*70)
        print("🎉 EXECUTION COMPLETE")
        print("="*70)

def main():
    print("="*70)
    print("MARL TRAFFIC CONTROL - REAL-TIME DASHBOARD")
    print("="*70)
    print("\nThis will:")
    print("1. 🚀 Start WebSocket server on ws://localhost:8765")
    print("2. 🚦 Start SUMO GUI with traffic control")
    print("3. 🤖 Load trained MARL agents")
    print("4. 📊 Send real-time data to dashboard")
    print("5. 🔄 Run continuously until Ctrl+C")
    print("="*70)
    
    print("\n📋 Before starting:")
    print("   • Make sure you have a dashboard running")
    print("   • Open dashboard.html in a browser")
    print("   • Or run a React dashboard on http://localhost:3000")
    print("="*70)
    
    input("\nPress Enter to start (Ctrl+C to cancel)...")
    
    executor = DashboardMARLExecutor()
    executor.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Execution cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()