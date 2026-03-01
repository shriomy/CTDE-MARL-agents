import traci
import sumolib
import numpy as np
from typing import Dict, List, Tuple, Any
from utils.traffic_actions import TrafficActions

class SumoEnv:
    """Wrapper for SUMO simulation environment for 4-way intersections"""
    
    def __init__(self, config_path: str, use_gui: bool = False):
        self.config_path = config_path
        self.use_gui = use_gui
        self.net = None
        self.tl_ids = ["J1_center", "J2_center"]  # ONLY these two traffic lights
        self.sumo_cmd = None
        self.episode_step = 0
        self.previous_phase = {tl_id: 0 for tl_id in self.tl_ids}
        
         # Track timing for each traffic light
        self.phase_start_time = {tl_id: 0 for tl_id in self.tl_ids}
        self.current_phase = {tl_id: 0 for tl_id in self.tl_ids}
        self.current_phase_duration = {tl_id: 0 for tl_id in self.tl_ids}
        self.last_switch_time = {tl_id: 0 for tl_id in self.tl_ids}

    def start(self):
        """Start SUMO simulation - FIXED for Windows"""
        if self.use_gui:
            sumo_binary = sumolib.checkBinary('sumo-gui')
        else:
            sumo_binary = sumolib.checkBinary('sumo')
        
        self.sumo_cmd = [sumo_binary, "-c", self.config_path]
        
        # Add these options for better compatibility
        self.sumo_cmd.extend([
            "--start",  # Start simulation immediately
            "--quit-on-end",  # Quit when simulation ends
            "--step-length", "1",
            "--no-warnings",  # Reduce warning output
        ])
        
        print(f"Starting SUMO with command: {' '.join(self.sumo_cmd)}")
        
        # Start TraCI
        traci.start(self.sumo_cmd)
        
        # Give it time to initialize
        import time
        time.sleep(2)
        
        print(f"SUMO started. Traffic lights: {self.tl_ids}")
        
    def close(self):
        """Close SUMO simulation"""
        try:
            traci.close()
            print("TraCI connection closed")
        except:
            pass
        
        # Also terminate the SUMO process if it exists
        if hasattr(self, 'sumo_process') and self.sumo_process:
            self.sumo_process.terminate()
            self.sumo_process.wait()
            print("SUMO process terminated")

    def reset(self):
        """Reset the simulation"""
        traci.load(self.sumo_cmd[1:])
        self.episode_step = 0
        self.phase_start_time = {tl_id: 0 for tl_id in self.tl_ids}
        self.current_phase_duration = {tl_id: 0 for tl_id in self.tl_ids}
        self.last_switch_time = {tl_id: 0 for tl_id in self.tl_ids}
        return self.get_state()
    
    def get_state(self) -> Dict[str, np.ndarray]:
        """Get state for each traffic light - FIXED for left-hand traffic"""
        state = {}
        current_time = traci.simulation.getTime()
        
        for tl_id in self.tl_ids:
            # Get lanes controlled by this traffic light
            controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
            
            # For 4 directions: West, North, East, South
            queue_lengths = np.zeros(4)  
            waiting_times = np.zeros(4)
            vehicle_counts = np.zeros(4)
            
            for lane_id in controlled_lanes:
                if "west" in lane_id.lower():
                    dir_idx = 0  # West
                elif "north" in lane_id.lower():
                    dir_idx = 1  # North
                elif "east" in lane_id.lower():
                    dir_idx = 2  # East
                elif "south" in lane_id.lower():
                    dir_idx = 3  # South
                else:
                    continue
                
                vehicles = traci.lane.getLastStepVehicleIDs(lane_id)
                vehicle_counts[dir_idx] += len(vehicles)
                
                # Calculate queue
                queue = 0
                waiting = 0
                for veh_id in vehicles:
                    speed = traci.vehicle.getSpeed(veh_id)
                    if speed < 0.1:
                        queue += 1
                        waiting += traci.vehicle.getWaitingTime(veh_id)
                
                queue_lengths[dir_idx] += queue
                waiting_times[dir_idx] += waiting
            
            # Get current phase
            current_phase = traci.trafficlight.getPhase(tl_id)
            phase_duration = traci.trafficlight.getPhaseDuration(tl_id)
            
            # CORRECTED: Determine which direction is currently green
            if current_phase == 0 or current_phase == 1:
                current_dir = 0  # West (Phase 0 = green, Phase 1 = yellow)
            elif current_phase == 2 or current_phase == 3:
                current_dir = 1  # North (Phase 2 = green, Phase 3 = yellow)
            elif current_phase == 4 or current_phase == 5:
                current_dir = 2  # East (Phase 4 = green, Phase 5 = yellow)
            elif current_phase == 6 or current_phase == 7:
                current_dir = 3  # South (Phase 6 = green, Phase 7 = yellow)
            else:
                current_dir = 1  # Default to North
            
            # Create state vector (15 features = 13 original + 2 timing)
            state_vector = np.array([
                # Queue lengths (4) - IMPORTANT: Keep order consistent
                queue_lengths[0] / 10.0,  # West (index 0)
                queue_lengths[1] / 10.0,  # North (index 1)
                queue_lengths[2] / 10.0,  # East (index 2)
                queue_lengths[3] / 10.0,  # South (index 3)
                
                # Waiting times (4) - Same order
                min(waiting_times[0] / 60.0, 1.0),  # West
                min(waiting_times[1] / 60.0, 1.0),  # North
                min(waiting_times[2] / 60.0, 1.0),  # East
                min(waiting_times[3] / 60.0, 1.0),  # South
                
                # Current green direction (4 one-hot) - CORRECTED
                1.0 if current_dir == 0 else 0.0,  # West green
                1.0 if current_dir == 1 else 0.0,  # North green
                1.0 if current_dir == 2 else 0.0,  # East green
                1.0 if current_dir == 3 else 0.0,  # South green
                
                # Phase duration (1) - Normalized to 0-1 (assuming max 60 seconds)
                min(phase_duration / 60.0, 1.0),
                
            ])
            
            # Update timing tracking
            if current_phase in [0, 2, 4, 6]:  # Green phase
                # Check if this is a new green phase (just switched from yellow)
                if self.current_phase.get(tl_id) in [1, 3, 5, 7]:
                    self.phase_start_time[tl_id] = current_time
                    self.last_switch_time[tl_id] = current_time
            
            self.current_phase[tl_id] = current_phase
            self.current_phase_duration[tl_id] = phase_duration
            
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
        vehicle_ids = traci.vehicle.getIDList()
        
        if not vehicle_ids:
            return 0.0
        
        # 1. Average waiting time (normalized)
        total_waiting = sum(traci.vehicle.getWaitingTime(v) for v in vehicle_ids)
        avg_waiting = total_waiting / len(vehicle_ids)
        
        # 2. Queue penalty
        total_queue = 0
        for tl_id in self.tl_ids:
            lanes = traci.trafficlight.getControlledLanes(tl_id)
            for lane in lanes:
                vehicles = traci.lane.getLastStepVehicleIDs(lane)
                for veh_id in vehicles:
                    if traci.vehicle.getSpeed(veh_id) < 0.1:
                        total_queue += 1
        
        # 3. Throughput bonus (vehicles that left)
        vehicles_left = traci.simulation.getDepartedNumber()
        
        # Calculate reward (should be in range [-10, 10])
        reward = (
            -avg_waiting * 0.1 +           # Penalize waiting
            -total_queue * 0.05 +          # Penalize queues
            vehicles_left * 0.01           # Reward throughput
        )
        
        return float(reward)
    
    def step(self, actions: Dict[str, int]) -> Tuple[Dict[str, np.ndarray], float, bool, Dict]:
        """Execute one step with timing constraints"""
        current_time = traci.simulation.getTime()
        
        for tl_id, action in actions.items():
            current_phase = traci.trafficlight.getPhase(tl_id)
            phase_duration = self.current_phase_duration[tl_id]
            
            # Use the updated TrafficActions with timing constraints
            new_phase, switched = TrafficActions.execute_action(
                tl_id, 
                action, 
                current_phase,
                phase_duration,
                self.last_switch_time
            )
            
            if switched:
                self.phase_start_time[tl_id] = current_time
                self.last_switch_time[tl_id] = current_time
            elif new_phase != current_phase:
                self.phase_start_time[tl_id] = current_time
        
        # Advance simulation
        traci.simulationStep()
        self.episode_step += 1
        
        # Get new state and reward
        next_state = self.get_state()
        reward = self.get_reward()
        done = self.episode_step >= 1800
        
        info = {
            'step': self.episode_step,
            'vehicle_count': len(traci.vehicle.getIDList()),
            'avg_speed': np.mean([traci.vehicle.getSpeed(veh_id) for veh_id in traci.vehicle.getIDList()]) if traci.vehicle.getIDList() else 0
        }
        
        return next_state, reward, done, info