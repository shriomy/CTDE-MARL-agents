"""
Traffic Actions with realistic timing constraints.
"""
import traci
import time

class TrafficActions:
    """Action definitions for PER-DIRECTION traffic control with realistic timing"""
    
    # Timing constraints (in seconds)
    MIN_GREEN_TIME = 10      # Minimum green time
    MAX_GREEN_TIME = 60      # Maximum green time
    YELLOW_TIME = 3         # Yellow transition time
    ALL_RED_TIME = 1         # All-red clearance time
    
    # Action space - same as before
    ACTIONS = {
        0: "SWITCH_TO_WEST_GREEN",
        1: "SWITCH_TO_NORTH_GREEN",  
        2: "SWITCH_TO_EAST_GREEN",
        3: "SWITCH_TO_SOUTH_GREEN",
        4: "EXTEND_CURRENT_PHASE"
    }
    
    # Phase mappings
    GREEN_PHASES = {
        0: 0,   # Action 0 -> West green (Phase 0)
        1: 2,   # Action 1 -> North green (Phase 2)
        2: 4,   # Action 2 -> East green (Phase 4)
        3: 6    # Action 3 -> South green (Phase 6)
    }
    
    YELLOW_PHASES = {
        0: 1,   # West yellow (Phase 1)
        1: 3,   # North yellow (Phase 3)
        2: 5,   # East yellow (Phase 5)
        3: 7    # South yellow (Phase 7)
    }
    
    @staticmethod
    def get_current_direction(current_phase: int) -> int:
        """Convert phase number to direction index"""
        if current_phase in [0, 1]:
            return 0  # West
        elif current_phase in [2, 3]:
            return 1  # North
        elif current_phase in [4, 5]:
            return 2  # East
        elif current_phase in [6, 7]:
            return 3  # South
        return 0  # Default to West
    
    @staticmethod
    def execute_action(tl_id: str, action: int, current_phase: int, 
                       phase_duration: float, last_switch_time: dict) -> tuple:
        """
        Execute action with realistic timing constraints.
        Returns: (new_phase, can_switch)
        """
        current_dir = TrafficActions.get_current_direction(current_phase)
        
        if action < 4:  # Switch to specific direction
            target_dir = action
            
            # Check if we're already in this direction
            if target_dir == current_dir:
                # Already in this direction, check if we can extend
                if current_phase in [0, 2, 4, 6]:  # Green phase
                    current_green_time = phase_duration
                    
                    # Check if we've exceeded max green time
                    if current_green_time >= TrafficActions.MAX_GREEN_TIME:
                        # Force switch to yellow
                        yellow_phase = TrafficActions.YELLOW_PHASES[current_dir]
                        traci.trafficlight.setPhase(tl_id, yellow_phase)
                        traci.trafficlight.setPhaseDuration(tl_id, TrafficActions.YELLOW_TIME)
                        print(f"[{tl_id}] Max green time reached ({TrafficActions.MAX_GREEN_TIME}s), switching to YELLOW")
                        return yellow_phase, True
                    
                    # Check minimum green time
                    if current_green_time < TrafficActions.MIN_GREEN_TIME:
                        # Can't switch yet, extend to minimum
                        remaining = TrafficActions.MIN_GREEN_TIME - current_green_time
                        traci.trafficlight.setPhaseDuration(tl_id, remaining + 5)
                        print(f"[{tl_id}] Extending green to meet minimum {TrafficActions.MIN_GREEN_TIME}s")
                        return current_phase, False
                    
                    # Normal extension
                    traci.trafficlight.setPhaseDuration(tl_id, 
                        traci.trafficlight.getPhaseDuration(tl_id) + 5)
                    return current_phase, False
                
                elif current_phase in [1, 3, 5, 7]:  # Yellow phase
                    # Just continue yellow
                    return current_phase, False
                
            else:  # Need to switch to different direction
                # Check if we can switch (must complete minimum green time)
                if current_phase in [0, 2, 4, 6]:  # Currently in green
                    current_green_time = phase_duration
                    
                    if current_green_time < TrafficActions.MIN_GREEN_TIME:
                        # Can't switch yet, need to complete minimum green
                        remaining = TrafficActions.MIN_GREEN_TIME - current_green_time
                        traci.trafficlight.setPhaseDuration(tl_id, remaining)
                        print(f"[{tl_id}] Can't switch yet, need {remaining:.1f}s more green time")
                        return current_phase, False
                    
                    # Can switch to yellow
                    yellow_phase = TrafficActions.YELLOW_PHASES[current_dir]
                    traci.trafficlight.setPhase(tl_id, yellow_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, TrafficActions.YELLOW_TIME)
                    print(f"[{tl_id}] Switching to {TrafficActions._dir_to_name(current_dir)} YELLOW")
                    return yellow_phase, True
                    
                elif current_phase in [1, 3, 5, 7]:  # Currently in yellow
                    # Check if yellow time is complete
                    if phase_duration < TrafficActions.YELLOW_TIME:
                        # Still in yellow phase
                        return current_phase, False
                    
                    # Yellow complete, switch to target green
                    green_phase = TrafficActions.GREEN_PHASES[target_dir]
                    traci.trafficlight.setPhase(tl_id, green_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, TrafficActions.MIN_GREEN_TIME)
                    print(f"[{tl_id}] Switching to {TrafficActions._dir_to_name(target_dir)} GREEN")
                    return green_phase, True
        
        elif action == 4:  # Extend current green
            if current_phase in [0, 2, 4, 6]:  # Only extend green phases
                current_green_time = phase_duration
                
                # Check max green time
                if current_green_time >= TrafficActions.MAX_GREEN_TIME:
                    # Force switch to yellow
                    yellow_phase = TrafficActions.YELLOW_PHASES[current_dir]
                    traci.trafficlight.setPhase(tl_id, yellow_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, TrafficActions.YELLOW_TIME)
                    print(f"[{tl_id}] Max green reached, forcing YELLOW")
                    return yellow_phase, True
                
                # Normal extension
                extension = 5
                new_duration = current_green_time + extension
                if new_duration > TrafficActions.MAX_GREEN_TIME:
                    extension = TrafficActions.MAX_GREEN_TIME - current_green_time
                
                traci.trafficlight.setPhaseDuration(tl_id,
                    traci.trafficlight.getPhaseDuration(tl_id) + extension)
                print(f"[{tl_id}] Extending green by {extension}s")
        
        return current_phase, False
    
    @staticmethod
    def _dir_to_name(direction):
        """Convert direction index to name"""
        names = ["WEST", "NORTH", "EAST", "SOUTH"]
        return names[direction] if 0 <= direction < 4 else "UNKNOWN"