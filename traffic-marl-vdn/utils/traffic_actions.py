"""
Traffic action execution with scalable, junction-specific phase metadata.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Set

import traci


@dataclass
class TrafficLightSpec:
    """Per-junction signal behavior used by the policy action executor."""

    action_to_green: Dict[int, Optional[int]]
    green_to_yellow: Dict[int, int]
    yellow_phases: Set[int]
    pedestrian_green_phases: Set[int]
    min_green: float
    max_green: float
    yellow_hold: float
    extension_step: float
    min_ped_green: float
    max_ped_green: float


class TrafficActions:
    """Action executor that preserves yellow transitions and timing constraints."""

    @staticmethod
    def _phase_elapsed(tl_id: str) -> float:
        """Get elapsed time in current phase with fallback for older APIs."""
        try:
            return float(traci.trafficlight.getSpentDuration(tl_id))
        except Exception:
            return float(traci.trafficlight.getPhaseDuration(tl_id))

    @staticmethod
    def _apply_phase(tl_id: str, phase_idx: int, duration: float) -> None:
        traci.trafficlight.setPhase(tl_id, phase_idx)
        traci.trafficlight.setPhaseDuration(tl_id, max(1.0, float(duration)))

    @staticmethod
    def execute_action(tl_id: str, action: int, spec: TrafficLightSpec) -> Dict[str, float]:
        """
        Execute one action at a traffic light using junction-specific rules.

        Returns metadata for diagnostics and reward shaping hooks.
        """
        current_phase = int(traci.trafficlight.getPhase(tl_id))
        elapsed = TrafficActions._phase_elapsed(tl_id)

        result = {
            "new_phase": float(current_phase),
            "switched": 0.0,
            "was_yellow": 1.0 if current_phase in spec.yellow_phases else 0.0,
            "target_action": float(action),
        }

        # If we are in yellow/all-red, complete the safety interval before any choice.
        if current_phase in spec.yellow_phases:
            if elapsed < spec.yellow_hold:
                return result

            # SUMO phase plans are ordered so yellow transitions naturally proceed to next phase.
            next_phase = (current_phase + 1) % len(traci.trafficlight.getAllProgramLogics(tl_id)[0].phases)
            min_hold = spec.min_ped_green if next_phase in spec.pedestrian_green_phases else spec.min_green
            TrafficActions._apply_phase(tl_id, next_phase, min_hold)
            result["new_phase"] = float(next_phase)
            result["switched"] = 1.0
            return result

        # Map policy action to a target green phase for this junction.
        if action == 4:
            target_green = current_phase
        else:
            target_green = spec.action_to_green.get(int(action), current_phase)
            if target_green is None:
                target_green = current_phase

        in_ped_phase = current_phase in spec.pedestrian_green_phases
        min_hold = spec.min_ped_green if in_ped_phase else spec.min_green
        max_hold = spec.max_ped_green if in_ped_phase else spec.max_green

        # If changing target, enforce min hold then go through yellow.
        if target_green != current_phase:
            if elapsed < min_hold:
                return result
            yellow_phase = spec.green_to_yellow.get(current_phase)
            if yellow_phase is None:
                TrafficActions._apply_phase(tl_id, target_green, min_hold)
                result["new_phase"] = float(target_green)
                result["switched"] = 1.0
                return result
            TrafficActions._apply_phase(tl_id, yellow_phase, spec.yellow_hold)
            result["new_phase"] = float(yellow_phase)
            result["switched"] = 1.0
            return result

        # Same target: extend if possible, otherwise trigger yellow to prevent very long greens.
        if elapsed >= max_hold:
            yellow_phase = spec.green_to_yellow.get(current_phase)
            if yellow_phase is not None:
                TrafficActions._apply_phase(tl_id, yellow_phase, spec.yellow_hold)
                result["new_phase"] = float(yellow_phase)
                result["switched"] = 1.0
            return result

        try:
            current_programmed = float(traci.trafficlight.getPhaseDuration(tl_id))
            traci.trafficlight.setPhaseDuration(tl_id, current_programmed + spec.extension_step)
        except Exception:
            pass

        return result
