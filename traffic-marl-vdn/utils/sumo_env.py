import traci
import sumolib
import numpy as np
import time
from typing import Dict, List, Tuple, Any

class SumoEnv:
    """Wrapper for SUMO simulation environment"""
    
    def __init__(self, config_path: str, use_gui: bool = False):
        self.config_path = config_path
        self.use_gui = use_gui
        self.net = None
        self.tl_ids = None
        self.sumo_cmd = None
        
    def start(self):
        """Start SUMO simulation"""
        if self.use_gui:
            sumo_binary = sumolib.checkBinary('sumo-gui')
        else:
            sumo_binary = sumolib.checkBinary('sumo')
        
        self.sumo_cmd = [sumo_binary, "-c", self.config_path]
        traci.start(self.sumo_cmd)
        
        # Load network
        self.net = traci.net
        
        # Get traffic light IDs
        self.tl_ids = list(traci.trafficlight.getIDList())
        print(f"Found traffic lights: {self.tl_ids}")
        
        # Initialize data structures
        self.episode_step = 0
        
    def close(self):
        """Close SUMO simulation"""
        traci.close()
        
    def reset(self):
        """Reset the simulation"""
        traci.load(self.sumo_cmd[1:])
        self.episode_step = 0
        return self.get_state()
    
    def get_state(self) -> Dict[str, np.ndarray]:
        """Get state for each traffic light"""
        state = {}
        
        for tl_id in self.tl_ids:
            # Get lanes controlled by this traffic light
            controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
            
            # Calculate queue length and waiting time for each lane
            queue_lengths = []
            waiting_times = []
            vehicle_counts = []
            
            for lane_id in controlled_lanes:
                # Get vehicles on this lane
                vehicles = traci.lane.getLastStepVehicleIDs(lane_id)
                vehicle_count = len(vehicles)
                vehicle_counts.append(vehicle_count)
                
                # Calculate queue length (vehicles with speed < 0.1 m/s)
                queue = 0
                waiting = 0
                for veh_id in vehicles:
                    speed = traci.vehicle.getSpeed(veh_id)
                    if speed < 0.1:
                        queue += 1
                        waiting += traci.vehicle.getWaitingTime(veh_id)
                
                queue_lengths.append(queue)
                waiting_times.append(waiting)
            
            # Get current phase
            current_phase = traci.trafficlight.getPhase(tl_id)
            phase_duration = traci.trafficlight.getPhaseDuration(tl_id)
            
            # Normalize state values
            max_vehicles_per_lane = 20  # Assumption
            
            # Create state vector
            state_vector = np.array([
                np.mean(vehicle_counts) / max_vehicles_per_lane,
                np.mean(queue_lengths) / max_vehicles_per_lane,
                np.mean(waiting_times) / 100.0,  # Normalize by 100 seconds
                current_phase / 4.0,  # Assuming 4 phases
                phase_duration / 60.0  # Normalize by 60 seconds
            ])
            
            state[tl_id] = state_vector
            
        return state
    
    def get_reward(self) -> float:
        """Calculate global reward based on waiting time"""
        total_waiting_time = 0
        
        # Get waiting time for all vehicles in the network
        vehicle_ids = traci.vehicle.getIDList()
        for veh_id in vehicle_ids:
            total_waiting_time += traci.vehicle.getWaitingTime(veh_id)
        
        # Negative reward: we want to minimize waiting time
        reward = -total_waiting_time / max(len(vehicle_ids), 1)
        return reward
    
    def step(self, actions: Dict[str, int]) -> Tuple[Dict[str, np.ndarray], float, bool, Dict]:
        """
        Execute one step in the environment
        
        Args:
            actions: Dictionary mapping traffic light ID to action index
            
        Returns:
            next_state: New state after action
            reward: Global reward
            done: Whether episode is done
            info: Additional info
        """
        # Apply actions to traffic lights
        for tl_id, action in actions.items():
            if action == 0:
                # Keep current phase
                pass
            elif action == 1:
                # Switch to next phase
                current_phase = traci.trafficlight.getPhase(tl_id)
                next_phase = (current_phase + 1) % 4  # Assuming 4 phases
                traci.trafficlight.setPhase(tl_id, next_phase)
        
        # Advance simulation by 1 second
        traci.simulationStep()
        self.episode_step += 1
        
        # Get new state and reward
        next_state = self.get_state()
        reward = self.get_reward()
        
        # Check if episode is done
        done = self.episode_step >= 3600  # 1 hour simulation
        
        # Additional info
        info = {
            'step': self.episode_step,
            'vehicle_count': len(traci.vehicle.getIDList())
        }
        
        return next_state, reward, done, info