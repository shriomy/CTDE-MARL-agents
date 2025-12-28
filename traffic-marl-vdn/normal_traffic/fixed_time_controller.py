"""
Fixed-time traffic light controller with deterministic timing.
"""
import os
import sys
import time
import json
import traci
import sumolib
import numpy as np
from datetime import datetime

class FixedTimeController:
    """Fixed-time traffic light controller with predefined cycle"""
    
    def __init__(self, config_path: str, use_gui: bool = True):
        self.config_path = config_path
        self.use_gui = use_gui
        self.sumo_cmd = None
        self.tl_ids = ["J1_center", "J2_center"]
        
        # Fixed timing schedule (in seconds)
        self.cycle = {
            'west': 30,    # Green time for West
            'north': 30,   # Green time for North
            'east': 30,    # Green time for East
            'south': 30,   # Green time for South
            'yellow': 3    # Yellow time between phases
        }
        
        # Current state
        self.current_phase = {tl_id: 0 for tl_id in self.tl_ids}
        self.phase_start_time = {tl_id: 0 for tl_id in self.tl_ids}
        self.cycle_position = {tl_id: 0 for tl_id in self.tl_ids}
        
        # Metrics
        self.metrics = {
            'step': 0,
            'queue_history': [],
            'waiting_history': [],
            'vehicle_history': [],
            'speed_history': [],
            'reward_history': []
        }
        
        print(f"Fixed-time controller initialized with {len(self.tl_ids)} traffic lights")
    
    def start(self):
        """Start SUMO simulation"""
        if self.use_gui:
            sumo_binary = sumolib.checkBinary('sumo-gui')
        else:
            sumo_binary = sumolib.checkBinary('sumo')
        
        # Add --start flag to start simulation immediately
        self.sumo_cmd = [sumo_binary, "-c", self.config_path, "--start", "--quit-on-end"]
        
        # Start SUMO with TraCI
        traci.start(self.sumo_cmd)
        
        # Initialize traffic lights with proper timing
        for tl_id in self.tl_ids:
            traci.trafficlight.setPhase(tl_id, 0)  # Start with West green
            traci.trafficlight.setPhaseDuration(tl_id, self.cycle['west'])
            self.phase_start_time[tl_id] = traci.simulation.getTime()
        
        print(f"SUMO started with fixed-time controller")
        print(f"Traffic lights: {self.tl_ids}")
        print(f"Initial phase: WEST (30s)")
        
        # Check if vehicles are loaded
        vehicle_count = traci.vehicle.getIDCount()
        print(f"Initial vehicles: {vehicle_count}")
        
        # If no vehicles, the route file might not be loading properly
        if vehicle_count == 0:
            print("⚠ WARNING: No vehicles detected!")
            print("Check if route file is properly configured in .sumocfg")
    
    def close(self):
        """Close SUMO simulation"""
        traci.close()
    
    def reset(self):
        """Reset simulation"""
        self.close()
        time.sleep(1)
        self.start()
        self.metrics['step'] = 0
        print("Simulation reset")
    
    def update_lights(self):
        """Update traffic lights based on fixed timing"""
        current_time = traci.simulation.getTime()
        
        for tl_id in self.tl_ids:
            phase_duration = current_time - self.phase_start_time[tl_id]
            current_phase = self.current_phase[tl_id]
            
            # Check if it's time to switch phase
            if current_phase in [0, 2, 4, 6]:  # Green phases
                green_time = self._get_green_time_for_phase(current_phase)
                if phase_duration >= green_time:
                    # Switch to yellow
                    next_phase = current_phase + 1
                    traci.trafficlight.setPhase(tl_id, next_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, self.cycle['yellow'])
                    self.current_phase[tl_id] = next_phase
                    self.phase_start_time[tl_id] = current_time
                    print(f"[{tl_id}] Switching to YELLOW after {green_time}s green")
                    
            elif current_phase in [1, 3, 5, 7]:  # Yellow phases
                if phase_duration >= self.cycle['yellow']:
                    # Switch to next green
                    next_green = (current_phase + 1) % 8
                    next_green_time = self._get_green_time_for_phase(next_green)
                    traci.trafficlight.setPhase(tl_id, next_green)
                    traci.trafficlight.setPhaseDuration(tl_id, next_green_time)
                    self.current_phase[tl_id] = next_green
                    self.phase_start_time[tl_id] = current_time
                    self.cycle_position[tl_id] = (self.cycle_position[tl_id] + 1) % 4
                    
                    direction = self._phase_to_direction(next_green)
                    print(f"[{tl_id}] Switching to {direction} GREEN ({next_green_time}s)")
    
    def _get_green_time_for_phase(self, phase):
        """Get green time for a given phase number"""
        if phase == 0:  # West green
            return self.cycle['west']
        elif phase == 2:  # North green
            return self.cycle['north']
        elif phase == 4:  # East green
            return self.cycle['east']
        elif phase == 6:  # South green
            return self.cycle['south']
        return 30  # Default
    
    def _phase_to_direction(self, phase):
        """Convert phase number to direction name"""
        if phase == 0 or phase == 1:
            return "WEST"
        elif phase == 2 or phase == 3:
            return "NORTH"
        elif phase == 4 or phase == 5:
            return "EAST"
        elif phase == 6 or phase == 7:
            return "SOUTH"
        return "UNKNOWN"
    
    def get_traffic_state(self):
        """Get current traffic state for all intersections"""
        state = {}
        
        for tl_id in self.tl_ids:
            # Get lanes controlled by this traffic light
            controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
            
            # Calculate queue lengths and waiting times per direction
            queue_lengths = np.zeros(4)  # West, North, East, South
            waiting_times = np.zeros(4)
            
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
            phase_duration = traci.simulation.getTime() - self.phase_start_time[tl_id]
            
            # Determine current direction
            current_dir = self._phase_to_direction_index(current_phase)
            
            state[tl_id] = {
                'queues': queue_lengths.tolist(),
                'waits': waiting_times.tolist(),
                'current_phase': int(current_phase),
                'current_direction': int(current_dir),
                'phase_duration': float(phase_duration),
                'cycle_position': int(self.cycle_position[tl_id])
            }
        
        return state
    
    def _phase_to_direction_index(self, phase):
        """Convert phase number to direction index"""
        if phase == 0 or phase == 1:
            return 0  # West
        elif phase == 2 or phase == 3:
            return 1  # North
        elif phase == 4 or phase == 5:
            return 2  # East
        elif phase == 6 or phase == 7:
            return 3  # South
        return 0
    
    def get_performance_metrics(self):
        """Calculate performance metrics"""
        vehicle_ids = traci.vehicle.getIDList()
        
        if not vehicle_ids:
            return {
                'avg_waiting': 0,
                'total_queue': 0,
                'vehicles_left': 0,
                'reward': 0,
                'vehicle_count': 0,
                'avg_speed': 0,
                'step': self.metrics['step']
            }
        
        # Average waiting time
        total_waiting = sum(traci.vehicle.getWaitingTime(v) for v in vehicle_ids)
        avg_waiting = total_waiting / len(vehicle_ids)
        
        # Queue penalty
        total_queue = 0
        for tl_id in self.tl_ids:
            lanes = traci.trafficlight.getControlledLanes(tl_id)
            for lane in lanes:
                vehicles = traci.lane.getLastStepVehicleIDs(lane)
                for veh_id in vehicles:
                    if traci.vehicle.getSpeed(veh_id) < 0.1:
                        total_queue += 1
        
        # Throughput
        vehicles_left = traci.simulation.getDepartedNumber()
        
        # Average speed
        avg_speed = np.mean([traci.vehicle.getSpeed(veh_id) for veh_id in vehicle_ids])
        
        # Calculate reward (same formula as MARL for fair comparison)
        reward = (
            -avg_waiting * 0.1 +           # Penalize waiting
            -total_queue * 0.05 +          # Penalize queues
            vehicles_left * 0.01           # Reward throughput
        )
        
        return {
            'avg_waiting': float(avg_waiting),
            'total_queue': int(total_queue),
            'vehicles_left': int(vehicles_left),
            'reward': float(reward),
            'vehicle_count': len(vehicle_ids),
            'avg_speed': float(avg_speed),
            'step': self.metrics['step']
        }
    
    def step(self):
        """Execute one simulation step"""
        # Update traffic lights
        self.update_lights()
        
        # Advance simulation
        traci.simulationStep()
        self.metrics['step'] += 1
        
        # Get state and metrics
        state = self.get_traffic_state()
        metrics = self.get_performance_metrics()
        
        # Update history
        self.metrics['queue_history'].append(metrics['total_queue'])
        self.metrics['waiting_history'].append(metrics['avg_waiting'])
        self.metrics['vehicle_history'].append(metrics['vehicle_count'])
        self.metrics['speed_history'].append(metrics['avg_speed'])
        self.metrics['reward_history'].append(metrics['reward'])
        
        # Debug: Print vehicle count every 100 steps
        if self.metrics['step'] % 100 == 0:
            print(f"Step {self.metrics['step']}: {metrics['vehicle_count']} vehicles, "
                  f"Reward: {metrics['reward']:.2f}")
        
        return state, metrics
    
    def run_for_steps(self, num_steps):
        """Run simulation for specified number of steps"""
        print(f"Running fixed-time controller for {num_steps} steps...")
        
        for step in range(num_steps):
            state, metrics = self.step()
            yield step, state, metrics
        
        print(f"Completed {num_steps} steps")
    
    def get_dashboard_data(self, state, metrics):
        """Format data for dashboard"""
        step_data = {
            'step': metrics['step'],
            'reward': metrics['reward'],
            'total_reward': sum(self.metrics['reward_history']),
            'vehicle_count': metrics['vehicle_count'],
            'avg_speed': metrics['avg_speed'],
            'avg_waiting': metrics['avg_waiting'],
            'total_queue': metrics['total_queue'],
            'vehicles_left': metrics['vehicles_left'],
            'timestamp': time.time(),
            'agents': {}
        }
        
        # Add agent data
        for tl_id, tl_state in state.items():
            step_data['agents'][tl_id] = {
                'action': tl_state['current_direction'],  # Current green direction
                'action_name': self._direction_to_name(tl_state['current_direction']),
                'queues': tl_state['queues'],
                'waits': tl_state['waits'],
                'current_phase': tl_state['current_phase'],
                'phase_duration': tl_state['phase_duration'],
                'cycle_position': tl_state['cycle_position']
            }
        
        return step_data
    
    def _direction_to_name(self, direction):
        """Convert direction index to name"""
        directions = ["WEST", "NORTH", "EAST", "SOUTH"]
        return directions[direction] if 0 <= direction < 4 else "UNKNOWN"