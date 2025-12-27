# In utils/sumo_env.py, update the get_state method:

def get_state(self) -> Dict[str, np.ndarray]:
    """Get state for each traffic light - UPDATED FOR 4-WAY INTERSECTIONS"""
    state = {}
    
    # Your traffic light IDs from the network
    self.tl_ids = ["J1_center", "J2_center"]  # Add this if not in __init__
    
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