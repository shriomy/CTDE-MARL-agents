import traci

class TrafficActions:
    """Action definitions for PER-DIRECTION traffic control"""
    
    # Action space matches sumo_env_new.py
    ACTIONS = {
        0: "SWITCH_TO_WEST_GREEN",    # Action 0 = West
        1: "SWITCH_TO_NORTH_GREEN",   # Action 1 = North  
        2: "SWITCH_TO_EAST_GREEN",    # Action 2 = East
        3: "SWITCH_TO_SOUTH_GREEN",   # Action 3 = South
        4: "EXTEND_CURRENT_PHASE"     # Action 4 = Extend
    }
    
    # CORRECTED: Map actions to actual phase numbers
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
        return 1 
    
    @staticmethod
    def execute_action(tl_id: str, action: int, current_phase: int) -> int:
        """Execute action and return new phase"""
        current_dir = TrafficActions.get_current_direction(current_phase)
        
        if action < 4:  # Switch to specific direction
            target_dir = action
            if target_dir == current_dir:
                # Already in this direction, extend it
                if current_phase in [0, 2, 4, 6]:  # Green phase
                    traci.trafficlight.setPhaseDuration(tl_id, 
                        traci.trafficlight.getPhaseDuration(tl_id) + 5)
                return current_phase
            else:
                # Need to switch directions
                if current_phase in [0, 2, 4, 6]:  # Currently in green
                    # Switch to yellow first
                    yellow_phase = TrafficActions.YELLOW_PHASES[current_dir]
                    traci.trafficlight.setPhase(tl_id, yellow_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, 3)
                    return yellow_phase
                elif current_phase in [1, 3, 5, 7]:  # Currently in yellow
                    # Switch to target green
                    green_phase = TrafficActions.GREEN_PHASES[target_dir]
                    traci.trafficlight.setPhase(tl_id, green_phase)
                    traci.trafficlight.setPhaseDuration(tl_id, 10)
                    return green_phase
        elif action == 4:  # Extend current green
            if current_phase in [0, 2, 4, 6]:  # Only extend green phases
                traci.trafficlight.setPhaseDuration(tl_id,
                    traci.trafficlight.getPhaseDuration(tl_id) + 5)
        
        return current_phase