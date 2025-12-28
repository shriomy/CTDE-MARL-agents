import traci
import sumolib
import numpy as np
import json
import torch
import os
import sys
from datetime import datetime

# Add parent directory to path to import your modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from agents.multi_agent_system import MultiAgentSystem
    from utils.sumo_env_new import SumoEnv
    print("Successfully imported MARL modules")
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the correct directory")
    sys.exit(1)

class Evaluator:
    def __init__(self, config_path="sumo_configs/1x2.sumocfg"):
        # Check if config file exists
        if not os.path.exists(config_path):
            print(f"ERROR: Config file not found at {config_path}")
            print(f"Current working directory: {os.getcwd()}")
            # Try alternative path
            alt_path = os.path.join("sumo_configs", "1x2.sumocfg")
            if os.path.exists(alt_path):
                config_path = alt_path
                print(f"Found config at: {config_path}")
            else:
                raise FileNotFoundError(f"Cannot find SUMO config file")
        
        self.config_path = config_path
        print(f"Evaluator initialized with config: {config_path}")
    
    def run_fixed_time_baseline(self, phase_duration=30):
        """Fixed-time controller baseline for 4-phase system"""
        print(f"\nRunning fixed-time baseline with {phase_duration}s phases...")
        
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
            'vehicle_counts': [],
            'step_rewards': []
        }
        
        step = 0
        current_green_phase = 0  # Start with West green (phase 0)
        phase_timer = 0
        tl_ids = ["J1_center", "J2_center"]
        
        try:
            while step < 600:  # 10 minutes for faster evaluation
                # Fixed-time cycle: West(30) → North(30) → East(30) → South(30)
                phase_timer += 1
                
                # Switch phase when timer reaches duration
                if phase_timer >= phase_duration:
                    # Move to next phase in sequence: 0→2→4→6→0
                    if current_green_phase == 0:    # West
                        current_green_phase = 2      # North
                    elif current_green_phase == 2:  # North
                        current_green_phase = 4      # East
                    elif current_green_phase == 4:  # East
                        current_green_phase = 6      # South
                    else:                           # South
                        current_green_phase = 0      # West
                    
                    phase_timer = 0
                    # Add 3-second yellow phase before switching
                    yellow_phase = current_green_phase + 1
                    for tl_id in tl_ids:
                        traci.trafficlight.setPhase(tl_id, yellow_phase)
                        traci.trafficlight.setPhaseDuration(tl_id, 3)
                    
                    traci.simulationStep()
                    step += 1
                
                # Set green phase
                for tl_id in tl_ids:
                    traci.trafficlight.setPhase(tl_id, current_green_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, phase_duration - phase_timer)
                
                traci.simulationStep()
                step += 1
                
                # Calculate reward (using same logic as MARL for fair comparison)
                vehicles = traci.vehicle.getIDList()
                if vehicles:
                    # Calculate reward similar to your get_reward() function
                    total_waiting = sum(traci.vehicle.getWaitingTime(v) for v in vehicles)
                    avg_waiting = total_waiting / len(vehicles)
                    
                    # Queue penalty
                    total_queue = 0
                    for tl_id in tl_ids:
                        lanes = traci.trafficlight.getControlledLanes(tl_id)
                        for lane in lanes:
                            lane_vehicles = traci.lane.getLastStepVehicleIDs(lane)
                            for v in lane_vehicles:
                                if traci.vehicle.getSpeed(v) < 0.1:
                                    total_queue += 1
                    
                    # Throughput bonus
                    vehicles_left = traci.simulation.getDepartedNumber()
                    
                    # Same reward calculation as in sumo_env_new.py
                    reward = (
                        -avg_waiting * 0.1 +
                        -total_queue * 0.05 +
                        vehicles_left * 0.01
                    )
                    
                    metrics['total_reward'] += reward
                    metrics['step_rewards'].append(reward)
                    metrics['total_waiting'] += total_waiting
                    metrics['queue_lengths'].append(total_queue)
                
                metrics['vehicle_counts'].append(len(vehicles))
                
                if step % 60 == 0:  # Log every minute
                    print(f"  Step {step}/600, Vehicles: {len(vehicles)}")
                    
        except Exception as e:
            print(f"Error during fixed-time simulation: {e}")
            import traceback
            traceback.print_exc()
        finally:
            traci.close()
        
        # Calculate averages
        if step > 0:
            metrics['avg_waiting'] = metrics['total_waiting'] / step if metrics['total_waiting'] > 0 else 0
            metrics['avg_reward'] = np.mean(metrics['step_rewards']) if metrics['step_rewards'] else 0
        
        if metrics['queue_lengths']:
            metrics['avg_queue'] = np.mean(metrics['queue_lengths'])
            metrics['max_queue'] = np.max(metrics['queue_lengths'])
        
        if metrics['vehicle_counts']:
            metrics['avg_vehicles'] = np.mean(metrics['vehicle_counts'])
        
        print(f"  Fixed-time completed: Avg reward = {metrics.get('avg_reward', 0):.2f}")
        return metrics
    
    def evaluate_marl(self, model_path="models/final"):
        """Evaluate trained MARL controller"""
        print("\nEvaluating MARL controller...")
        
        # Check if model exists
        if not os.path.exists(model_path):
            print(f"ERROR: Model path not found: {model_path}")
            print("Available models:")
            for root, dirs, files in os.walk("models"):
                for file in files:
                    print(f"  {os.path.join(root, file)}")
            return {}
        
        # Initialize environment
        env = SumoEnv(self.config_path, use_gui=False)
        env.start()
        
        # Get state dimension from environment
        test_state = env.get_state()
        sample_agent = list(test_state.keys())[0]
        state_dim = len(test_state[sample_agent])
        
        print(f"State dimension: {state_dim}, Action dimension: 5")
        
        # Load trained agents
        agent_ids = env.tl_ids
        multi_agent = MultiAgentSystem(
            agent_ids=agent_ids,
            state_dim=state_dim,
            action_dim=5,  # FIXED: Should be 5, not 4
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
            'actions_taken': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0},  # 5 actions
            'vehicle_counts': [],
            'step_rewards': []
        }
        
        step = 0
        previous_phases = {}
        
        try:
            while step < 600:  # 10 minutes for fair comparison
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
                
                # Collect metrics
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
                    
                if step % 60 == 0:  # Log every minute
                    print(f"  Step {step}/600, Reward: {reward:.2f}, Vehicles: {len(vehicles)}")
                    
        except Exception as e:
            print(f"Error during MARL evaluation: {e}")
            import traceback
            traceback.print_exc()
        finally:
            env.close()
        
        # Calculate final metrics
        if step > 0:
            metrics['avg_waiting'] = metrics['total_waiting'] / step if metrics['total_waiting'] > 0 else 0
            metrics['avg_reward'] = np.mean(metrics['step_rewards']) if metrics['step_rewards'] else 0
            metrics['total_reward'] = np.sum(metrics['step_rewards'])
        
        if metrics['queue_lengths']:
            metrics['avg_queue'] = np.mean(metrics['queue_lengths'])
            metrics['max_queue'] = np.max(metrics['queue_lengths'])
        
        if metrics['vehicle_counts']:
            metrics['avg_vehicles'] = np.mean(metrics['vehicle_counts'])
        
        print(f"  MARL completed: Avg reward = {metrics.get('avg_reward', 0):.2f}")
        return metrics
    
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
        results_dir = "evaluation_results"
        os.makedirs(results_dir, exist_ok=True)
        results_file = os.path.join(results_dir, f"evaluation_{timestamp}.json")
        
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
        print("PERFORMANCE COMPARISON (10-minute simulation)")
        print("=" * 60)
        
        print("\nMETRIC                    | Fixed-time (30s) | Fixed-time (40s) | MARL Controller")
        print("-" * 85)
        
        # Average waiting time per vehicle
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
        
        # Average reward
        ft30_reward = results.get('fixed_time_30s', {}).get('avg_reward', 0)
        ft40_reward = results.get('fixed_time_40s', {}).get('avg_reward', 0)
        marl_reward = results.get('marl', {}).get('avg_reward', 0)
        
        print(f"Avg Reward per Step      | {ft30_reward:16.2f} | {ft40_reward:16.2f} | {marl_reward:16.2f}")
        
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
                action_names = ["West Green", "North Green", "East Green", "South Green", "Extend Current"]
                for i, name in enumerate(action_names):
                    count = actions.get(i, 0)
                    percentage = (count / total_actions * 100) if total_actions > 0 else 0
                    print(f"    {name}: {count} ({percentage:.1f}%)")
        
        # Improvement calculation
        if ft30_reward != 0:
            improvement = ((marl_reward - ft30_reward) / abs(ft30_reward) * 100)
            print(f"\nMARL Improvement over Fixed-time (30s):")
            print(f"  Reward Improvement: {improvement:.1f}%")
            
            if improvement > 0:
                print(f"  ✓ MARL performs BETTER than fixed-time")
            elif improvement < 0:
                print(f"  ✗ MARL performs WORSE than fixed-time")
            else:
                print(f"  = MARL performs EQUALLY to fixed-time")
        
        print(f"\nNote: Higher reward is better (closer to 0 or positive)")
        print(f"      Your MARL was trained to achieve reward ~-450 per episode")

if __name__ == "__main__":
    try:
        evaluator = Evaluator(config_path="sumo_configs/1x2.sumocfg")
        results = evaluator.run_comparison()
        
        # Save visualization data
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        viz_file = f"comparison_data_{timestamp}.json"
        
        viz_data = {
            "controllers": ["Fixed-time 30s", "Fixed-time 40s", "MARL"],
            "avg_waiting": [
                results.get('fixed_time_30s', {}).get('avg_waiting', 0),
                results.get('fixed_time_40s', {}).get('avg_waiting', 0),
                results.get('marl', {}).get('avg_waiting', 0)
            ],
            "avg_queue": [
                results.get('fixed_time_30s', {}).get('avg_queue', 0),
                results.get('fixed_time_40s', {}).get('avg_queue', 0),
                results.get('marl', {}).get('avg_queue', 0)
            ],
            "avg_reward": [
                results.get('fixed_time_30s', {}).get('avg_reward', 0),
                results.get('fixed_time_40s', {}).get('avg_reward', 0),
                results.get('marl', {}).get('avg_reward', 0)
            ]
        }
        
        with open(viz_file, 'w') as f:
            json.dump(viz_data, f, indent=2)
        
        print(f"\nVisualization data saved to: {viz_file}")
        print("You can use this for your React dashboard!")
        
    except Exception as e:
        print(f"Evaluation failed: {e}")
        import traceback
        traceback.print_exc()