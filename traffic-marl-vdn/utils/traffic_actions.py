# Create a new file: utils/traffic_actions.py

class TrafficActions:
    """Action definitions for 4-way intersections"""
    
    # Action space for a 4-way intersection
    ACTIONS = {
        0: "EXTEND_CURRENT_PHASE",     # Keep current phase longer
        1: "SWITCH_TO_NS_GREEN",       # Switch to North-South green
        2: "SWITCH_TO_EW_GREEN",       # Switch to East-West green
        3: "EMERGENCY_PRIORITY"        # Emergency vehicle priority
    }
    
    # Phase mapping for SUMO
    PHASE_MAP = {
        "NS_GREEN": 0,      # North-South green, East-West red
        "NS_YELLOW": 1,     # North-South yellow
        "EW_GREEN": 2,      # East-West green, North-South red
        "EW_YELLOW": 3      # East-West yellow
    }
    
    @staticmethod
    def execute_action(tl_id: str, action: int, current_phase: int) -> int:
        """Execute action and return new phase"""
        if action == 0:  # Extend current phase
            traci.trafficlight.setPhaseDuration(tl_id, 10)  # Extend by 10 seconds
            return current_phase
            
        elif action == 1:  # Switch to NS green
            if current_phase != 0:
                traci.trafficlight.setPhase(tl_id, 0)
                return 0
                
        elif action == 2:  # Switch to EW green
            if current_phase != 2:
                traci.trafficlight.setPhase(tl_id, 2)
                return 2
                
        elif action == 3:  # Emergency priority
            # Force green in specific direction (simplified)
            traci.trafficlight.setPhase(tl_id, 0)  # Force NS green
            traci.trafficlight.setPhaseDuration(tl_id, 20)
            return 0
            
        return current_phase