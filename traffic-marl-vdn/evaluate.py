import traci
import sumolib
import numpy as np
import json
import torch
import os
from datetime import datetime
from agents.multi_agent_system import MultiAgentSystem
from utils.sumo_env import SumoEnv

class Evaluator:
    def __init__(self, config_path="sumo_configs/1x2.sumocfg"):
        self.config_path = config_path
        
    def run_fixed_time_baseline(self, phase_duration=30):
        """Fixed-time controller baseline"""
        print(f"Running fixed-time baseline with {phase_duration}s phases...")
        
        if self.config_path is None:
            print("Error: config_path is None")
            return {}
            
        try:
            traci.start([sumolib.checkBinary('sumo'), "-c", self.config_path])
        except Exception as e:
            print(f"Failed to start SUMO: {e}")
            return {}
        
        metrics = {
            'total_waiting': 0,
            'avg_waiting': 0,
            'queue_lengths': [],
            'travel_times': [],
            'total_reward': 0,
            'vehicle_counts': []
        }
        
        step = 0
        phase = 0
        tl_ids = ["J1_center", "J2_center"]
        
        try:
            while step < 1800:  # Reduced to 30 minutes for faster evaluation
                # Change phase every phase_duration seconds
                if step % phase_duration == 0:
                    phase = (phase + 2) % 4  # Switch between NS and EW (0 and 2)
                    for tl_id in tl_ids:
                        traci.trafficlight.setPhase(tl_id, phase)
                
                traci.simulationStep()
                step += 1
                
                # Collect metrics
                vehicles = traci.vehicle.getIDList()
                metrics['vehicle_counts'].append(len(vehicles))
                
                if vehicles:
                    waiting_times = [traci.vehicle.getWaitingTime(v) for v in vehicles]
                    metrics['total_waiting'] += sum(waiting_times)
                    
                    # Queue length
                    queue = 0
                    for tl_id in tl_ids:
                        lanes = traci.trafficlight.getControlledLanes(tl_id)
                        for lane in lanes:
                            lane_vehicles = traci.lane.getLastStepVehicleIDs(lane)
                            for v in lane_vehicles:
                                if traci.vehicle.getSpeed(v) < 0.1:
                                    queue += 1
                    metrics['queue_lengths'].append(queue)
        except Exception as e:
            print(f"Error during fixed-time simulation: {e}")
        finally:
            traci.close()
        
        # Calculate averages
        if metrics['queue_lengths']:
            metrics['avg_queue'] = np.mean(metrics['queue_lengths'])
            metrics['max_queue'] = np.max(metrics['queue_lengths'])
        
        if step > 0:
            metrics['avg_waiting'] = metrics['total_waiting'] / step
            metrics['avg_vehicles'] = np.mean(metrics['vehicle_counts'])
        
        return metrics
    
    def evaluate_marl(self, model_path="models/final"):
        """Evaluate trained MARL controller"""
        print("Evaluating MARL controller...")
        
        # First, get the state dimension by checking the saved model
        state_dim = self.get_state_dim_from_model(model_path)
        if state_dim is None:
            # Fallback: check the environment
            env = SumoEnv(self.config_path, use_gui=False)
            env.start()
            test_state = env.get_state()
            state_dim = len(list(test_state.values())[0])
            env.close()
        
        print(f"Detected state dimension: {state_dim}")
        
        # Initialize environment
        env = SumoEnv(self.config_path, use_gui=False)
        env.start()
        
        # Load trained agents with correct state dimension
        agent_ids = env.tl_ids
        multi_agent = MultiAgentSystem(
            agent_ids=agent_ids,
            state_dim=state_dim,
            action_dim=4,
            config={"enable_communication": False}
        )
        
        # Load models
        success = multi_agent.load_models(model_path)
        if not success:
            print("Failed to load models")
            env.close()
            return {}
        
        # Set epsilon to 0 for pure exploitation
        for agent in multi_agent.agents.values():
            agent.epsilon = 0.0
        
        state = env.reset()
        metrics = {
            'total_waiting': 0,
            'queue_lengths': [],
            'phase_changes': {tl_id: [] for tl_id in agent_ids},
            'actions_taken': {0: 0, 1: 0, 2: 0, 3: 0},
            'vehicle_counts': [],
            'step_rewards': []
        }
        
        step = 0
        previous_phases = {}
        
        try:
            while step < 1800:  # 30 minutes
                # Get actions from MARL agents
                actions = multi_agent.act(state, training_mode=False)
                
                # Track actions
                for action in actions.values():
                    if action in metrics['actions_taken']:
                        metrics['actions_taken'][action] += 1
                
                # Execute and get next state
                next_state, reward, done, info = env.step(actions)
                state = next_state
                
                metrics['step_rewards'].append(reward)
                
                # Collect waiting times
                vehicles = traci.vehicle.getIDList()
                metrics['vehicle_counts'].append(len(vehicles))
                
                if vehicles:
                    waiting_times = [traci.vehicle.getWaitingTime(v) for v in vehicles]
                    metrics['total_waiting'] += sum(waiting_times)
                    
                    # Queue length
                    queue = 0
                    for tl_id in agent_ids:
                        lanes = traci.trafficlight.getControlledLanes(tl_id)
                        for lane in lanes:
                            lane_vehicles = traci.lane.getLastStepVehicleIDs(lane)
                            for v in lane_vehicles:
                                if traci.vehicle.getSpeed(v) < 0.1:
                                    queue += 1
                    metrics['queue_lengths'].append(queue)
                
                # Track phase changes
                for tl_id in agent_ids:
                    current_phase = traci.trafficlight.getPhase(tl_id)
                    if tl_id not in previous_phases or previous_phases[tl_id] != current_phase:
                        metrics['phase_changes'][tl_id].append((step, current_phase))
                    previous_phases[tl_id] = current_phase
                
                step += 1
                
                if done:
                    break
                    
                if step % 300 == 0:  # Log every 5 minutes
                    print(f"  Step {step}/{1800}, Vehicles: {len(vehicles)}")
                    
        except Exception as e:
            print(f"Error during MARL evaluation: {e}")
        finally:
            env.close()
        
        # Calculate final metrics
        if step > 0:
            metrics['avg_waiting'] = metrics['total_waiting'] / step
            metrics['avg_reward'] = np.mean(metrics['step_rewards']) if metrics['step_rewards'] else 0
            metrics['total_reward'] = np.sum(metrics['step_rewards'])
        
        if metrics['queue_lengths']:
            metrics['avg_queue'] = np.mean(metrics['queue_lengths'])
            metrics['max_queue'] = np.max(metrics['queue_lengths'])
        
        if metrics['vehicle_counts']:
            metrics['avg_vehicles'] = np.mean(metrics['vehicle_counts'])
        
        return metrics
    
    def get_state_dim_from_model(self, model_path):
        """Extract state dimension from saved model"""
        try:
            # Check the first agent's model
            agent_files = [f for f in os.listdir(model_path) if f.endswith('_model.pth')]
            if not agent_files:
                return None
            
            first_agent_file = os.path.join(model_path, agent_files[0])
            checkpoint = torch.load(first_agent_file, map_location='cpu', weights_only=False)
            
            # The first layer weight shape is [64, state_dim]
            weight_shape = checkpoint['q_network_state_dict']['0.weight'].shape
            state_dim = weight_shape[1]  # Second dimension is input size
            
            return state_dim
            
        except Exception as e:
            print(f"Could not determine state dim from model: {e}")
            return None
    
    def run_comparison(self):
        """Run all evaluations and compare"""
        print("=" * 60)
        print("TRAFFIC CONTROLLER EVALUATION")
        print("=" * 60)
        
        results = {}
        
        # 1. Fixed-time baseline (30s)
        print("\n1. Testing Fixed-time Controller (30s phases)...")
        results['fixed_time_30s'] = self.run_fixed_time_baseline(phase_duration=30)
        
        # 2. Fixed-time baseline (40s)
        print("\n2. Testing Fixed-time Controller (40s phases)...")
        results['fixed_time_40s'] = self.run_fixed_time_baseline(phase_duration=40)
        
        # 3. Your MARL controller
        print("\n3. Testing MARL Controller...")
        results['marl'] = self.evaluate_marl(model_path="models/final")
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"evaluation_results_{timestamp}.json"
        
        # Convert numpy values to Python native types for JSON serialization
        def convert_for_json(obj):
            if isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_for_json(item) for item in obj]
            else:
                return obj
        
        with open(results_file, "w") as f:
            json.dump(convert_for_json(results), f, indent=2)
        
        print(f"\nResults saved to: {results_file}")
        
        # Print comparison
        self.print_comparison(results)
        
        return results
    
    def print_comparison(self, results):
        """Print formatted comparison"""
        print("\n" + "=" * 60)
        print("PERFORMANCE COMPARISON")
        print("=" * 60)
        
        print("\nMETRIC                    | Fixed-time (30s) | Fixed-time (40s) | MARL Controller")
        print("-" * 85)
        
        # Average waiting time
        ft30_wait = results.get('fixed_time_30s', {}).get('avg_waiting', 0)
        ft40_wait = results.get('fixed_time_40s', {}).get('avg_waiting', 0)
        marl_wait = results.get('marl', {}).get('avg_waiting', 0)
        
        print(f"Avg Waiting Time (s)     | {ft30_wait:16.2f} | {ft40_wait:16.2f} | {marl_wait:16.2f}")
        
        # Average queue length
        ft30_queue = results.get('fixed_time_30s', {}).get('avg_queue', 0)
        ft40_queue = results.get('fixed_time_40s', {}).get('avg_queue', 0)
        marl_queue = results.get('marl', {}).get('avg_queue', 0)
        
        print(f"Avg Queue Length         | {ft30_queue:16.2f} | {ft40_queue:16.2f} | {marl_queue:16.2f}")
        
        # Average vehicles
        ft30_veh = results.get('fixed_time_30s', {}).get('avg_vehicles', 0)
        ft40_veh = results.get('fixed_time_40s', {}).get('avg_vehicles', 0)
        marl_veh = results.get('marl', {}).get('avg_vehicles', 0)
        
        print(f"Avg Vehicles in System   | {ft30_veh:16.2f} | {ft40_veh:16.2f} | {marl_veh:16.2f}")
        
        # MARL specific stats
        if 'marl' in results:
            marl_results = results['marl']
            print(f"\nMARL Controller Statistics:")
            print(f"  Total Reward: {marl_results.get('total_reward', 0):.2f}")
            print(f"  Average Step Reward: {marl_results.get('avg_reward', 0):.3f}")
            
            total_phase_changes = sum(len(v) for v in marl_results.get('phase_changes', {}).values())
            print(f"  Total Phase Changes: {total_phase_changes}")
            
            actions = marl_results.get('actions_taken', {})
            total_actions = sum(actions.values())
            if total_actions > 0:
                print(f"  Action Distribution:")
                action_names = ["Extend", "NS Green", "EW Green", "Emergency"]
                for i, name in enumerate(action_names):
                    count = actions.get(i, 0)
                    percentage = (count / total_actions * 100) if total_actions > 0 else 0
                    print(f"    {name}: {count} ({percentage:.1f}%)")
        
        # Improvement calculation
        if ft30_wait > 0 and marl_wait > 0:
            improvement = ((ft30_wait - marl_wait) / ft30_wait * 100)
            print(f"\nMARL Improvement over Fixed-time (30s):")
            print(f"  Waiting Time Reduction: {improvement:.1f}%")
            
            if improvement > 0:
                print(f"  ✓ MARL performs BETTER than fixed-time")
            elif improvement < 0:
                print(f"  ✗ MARL performs WORSE than fixed-time")
            else:
                print(f"  = MARL performs EQUALLY to fixed-time")

if __name__ == "__main__":
    evaluator = Evaluator(config_path="sumo_configs/1x2.sumocfg")
    results = evaluator.run_comparison()
    