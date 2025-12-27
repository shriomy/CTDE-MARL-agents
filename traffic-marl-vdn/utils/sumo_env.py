import traci
import sumolib
import numpy as np
from typing import Dict, List, Tuple, Any

class SumoEnv:
    """Wrapper for SUMO simulation environment for 4-way intersections"""
    
    def __init__(self, config_path: str, use_gui: bool = False):
        self.config_path = config_path
        self.use_gui = use_gui
        self.net = None
        self.tl_ids = ["J1_center", "J2_center"]  # Your traffic light IDs
        self.sumo_cmd = None
        self.episode_step = 0
        
    def start(self):
        """Start SUMO simulation"""
        if self.use_gui:
            sumo_binary = sumolib.checkBinary('sumo-gui')
        else:
            sumo_binary = sumolib.checkBinary('sumo')
        
        self.sumo_cmd = [sumo_binary, "-c", self.config_path]
        traci.start(self.sumo_cmd)
        
        print(f"SUMO started. Traffic lights: {self.tl_ids}")
        
    def close(self):
        """Close SUMO simulation"""
        traci.close()
        
    def reset(self):
        """Reset the simulation"""
        traci.load(self.sumo_cmd[1:])
        self.episode_step = 0
        return self.get_state()
    
    def get_state(self) -> Dict[str, np.ndarray]:
        """Get state for each traffic light - UPDATED FOR 4-WAY INTERSECTIONS"""
        state = {}
        
        for tl_id in self.tl_ids:
            # Get lanes controlled by this traffic light
            controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
            
            # Group lanes by approach direction
            queue_by_direction = {"north": 0, "east": 0, "south": 0, "west": 0}
            waiting_by_direction = {"north": 0, "east": 0, "south": 0, "west": 0}
            
            for lane_id in controlled_lanes:
                # Extract direction from lane ID
                if "north" in lane_id.lower():
                    direction = "north"
                elif "east" in lane_id.lower():
                    direction = "east"
                elif "south" in lane_id.lower():
                    direction = "south"
                elif "west" in lane_id.lower():
                    direction = "west"
                else:
                    direction = "unknown"
                
                # Get vehicles on this lane
                vehicles = traci.lane.getLastStepVehicleIDs(lane_id)
                vehicle_count = len(vehicles)
                
                # Calculate queue (vehicles with speed < 0.1 m/s)
                queue = 0
                waiting = 0
                for veh_id in vehicles:
                    speed = traci.vehicle.getSpeed(veh_id)
                    if speed < 0.1:
                        queue += 1
                        waiting += traci.vehicle.getWaitingTime(veh_id)
                
                queue_by_direction[direction] += queue
                waiting_by_direction[direction] += waiting
            
            # Get current phase
            current_phase = traci.trafficlight.getPhase(tl_id)
            phase_duration = traci.trafficlight.getPhaseDuration(tl_id)
            
            # Create state vector (16 features)
            state_vector = np.array([
                # Queue lengths per direction (4)
                queue_by_direction["north"] / 20.0,  # Normalized
                queue_by_direction["east"] / 20.0,
                queue_by_direction["south"] / 20.0,
                queue_by_direction["west"] / 20.0,
                
                # Waiting times per direction (4)
                waiting_by_direction["north"] / 100.0,
                waiting_by_direction["east"] / 100.0,
                waiting_by_direction["south"] / 100.0,
                waiting_by_direction["west"] / 100.0,
                
                # Current phase info (3)
                current_phase / 8.0,  # Assuming up to 8 phases
                phase_duration / 60.0,
                1.0 if current_phase < 4 else 0.0,  # Is it N-S green?
                
                # Traffic density approaching (4)
                self._get_approaching_density(tl_id, "north"),
                self._get_approaching_density(tl_id, "east"),
                self._get_approaching_density(tl_id, "south"),
                self._get_approaching_density(tl_id, "west"),
                
                # Current simulation time (1) - for rush hour patterns
                traci.simulation.getTime() / 3600.0
            ])
            
            state[tl_id] = state_vector
        
        return state
    
    def _get_approaching_density(self, tl_id: str, direction: str) -> float:
        """Get density of vehicles approaching from given direction"""
        # Map direction to incoming edge IDs
        edge_map = {
            "J1_center": {
                "north": "J1_north_approach",
                "east": "J1_east_approach",  # From J2
                "south": "J1_south_approach",
                "west": "J1_west_approach"
            },
            "J2_center": {
                "north": "J2_north_approach",
                "east": "J2_east_approach",
                "south": "J2_south_approach",
                "west": "J2_west_approach"  # From J1
            }
        }
        
        try:
            edge_id = edge_map[tl_id][direction]
            vehicles = traci.edge.getLastStepVehicleIDs(edge_id)
            # Normalize by edge length and lanes
            return len(vehicles) / 50.0  # Assuming max 50 vehicles
        except:
            return 0.0
    
    def get_reward(self) -> float:
        """Calculate normalized global reward"""
        vehicle_ids = traci.vehicle.getIDList()
        
        if not vehicle_ids or len(vehicle_ids) < 5:
            return 0.0  # Neutral reward if few vehicles
    
        total_waiting = 0
        for veh_id in vehicle_ids:
            total_waiting += traci.vehicle.getWaitingTime(veh_id)
        
        # Normalize: -1 to 0 range
        avg_waiting = total_waiting / len(vehicle_ids)
        
        # Scale: -0.01 per second of average waiting
        # So if avg waiting = 10s → reward = -0.1
        # if avg waiting = 50s → reward = -0.5
        waiting_penalty = -avg_waiting * 0.01
        
        # Add bonus for keeping vehicles moving
        total_speed = 0
        for veh_id in vehicle_ids:
            total_speed += traci.vehicle.getSpeed(veh_id)
        avg_speed = total_speed / len(vehicle_ids)
        
        # Speed bonus: +0.01 per m/s of average speed
        speed_bonus = avg_speed * 0.02
        
        # Combined reward
        combined_reward = waiting_penalty + speed_bonus
        
        # Clip to reasonable range
        combined_reward = max(-1.0, min(0.0, combined_reward))
        
        return combined_reward
    
    def step(self, actions: Dict[str, int]) -> Tuple[Dict[str, np.ndarray], float, bool, Dict]:
        """
        Execute one step in the environment
        
        Args:
            actions: Dictionary mapping traffic light ID to action index
                    0: Extend current phase
                    1: Switch to NS green  
                    2: Switch to EW green
                    3: Emergency priority
            
        Returns:
            next_state: New state after action
            reward: Global reward
            done: Whether episode is done
            info: Additional info
        """
        # Apply actions to traffic lights
        for tl_id, action in actions.items():
            current_phase = traci.trafficlight.getPhase(tl_id)
            
            if action == 0:  # Extend current phase
                traci.trafficlight.setPhaseDuration(tl_id, 10)  # Extend by 10 seconds
                
            elif action == 1:  # Switch to NS green
                if current_phase != 0:
                    traci.trafficlight.setPhase(tl_id, 0)
                    
            elif action == 2:  # Switch to EW green
                if current_phase != 2:
                    traci.trafficlight.setPhase(tl_id, 2)
                    
            elif action == 3:  # Emergency priority
                # Force green in specific direction
                traci.trafficlight.setPhase(tl_id, 0)  # Force NS green
                traci.trafficlight.setPhaseDuration(tl_id, 20)
        
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