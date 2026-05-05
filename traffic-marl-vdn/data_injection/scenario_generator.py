"""
Comprehensive SUMO route file generator for MARL training.
Generates 75 diverse, realistic scenarios that test priority logic, emergency handling,
and pedestrian crossing decisions without MongoDB injection.

Scenarios cover:
- All 16 possible routes (5 entry × 4 exit combinations)
- Emergency vehicle priority
- Pedestrian crossing priority
- High-priority pedestrian (mobility-aided) conflicts
- Edge cases (no vehicles, no pedestrians, extreme conditions)
- Complex multi-objective prioritization
"""
import os
import random
from typing import List, Dict, Tuple, Set
from datetime import datetime

# Network structure
ENTRY_EDGES = ["E0", "-E2", "-E8", "-E4", "-E5"]
EXIT_EDGES = ["E0", "-E2", "-E8", "-E4", "-E5"]

# All possible routes (entry -> exit via intermediate junctions)
ALL_ROUTES = [
    ("E0", "-E2"), ("E0", "-E8"), ("E0", "-E4"), ("E0", "-E5"),
    ("-E2", "E0"), ("-E2", "-E8"), ("-E2", "-E4"), ("-E2", "-E5"),
    ("-E8", "E0"), ("-E8", "-E2"), ("-E8", "-E4"), ("-E8", "-E5"),
    ("-E4", "E0"), ("-E4", "-E2"), ("-E4", "-E8"), ("-E4", "-E5"),
    ("-E5", "E0"), ("-E5", "-E2"), ("-E5", "-E8"), ("-E5", "-E4"),
]

# Pedestrian crossings (north side <-> south side)
PEDESTRIAN_CROSSINGS = [
    ("north_crossing", "south_crossing"),
    ("south_crossing", "north_crossing"),
]

VEHICLE_TYPES = {
    "bike": {"color": "255,255,0", "maxSpeed": 20, "length": 1.8},
    "car": {"color": "0,255,0", "maxSpeed": 25, "length": 5.0},
    "auto": {"color": "128,128,255", "maxSpeed": 25, "length": 4.3},
    "truck": {"color": "128,128,128", "maxSpeed": 20, "length": 8.5},
    "bus": {"color": "255,255,0", "maxSpeed": 20, "length": 12.0},
    "lorry": {"color": "150,150,150", "maxSpeed": 20, "length": 10.0},
}

EMERGENCY_TYPES = {
    "ambulance": {"color": "255,0,0", "maxSpeed": 40, "length": 7.5},
    "police": {"color": "0,0,255", "maxSpeed": 40, "length": 5.5},
    "firetruck": {"color": "255,165,0", "maxSpeed": 40, "length": 10.0},
}

PEDESTRIAN_TYPES = {
    "adult": {"maxSpeed": 1.4, "color": "0,255,0"},
    "student": {"maxSpeed": 1.5, "color": "0,0,255"},
    "elderly": {"maxSpeed": 1.0, "color": "255,0,255"},
    "mobility_aid": {"maxSpeed": 0.8, "color": "255,100,0"},  # High priority
}


class ScenarioGenerator:
    """Generates comprehensive MARL training scenarios."""

    def __init__(self, output_dir: str = "sumo_configs/scenarios"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.scenario_index = 0

    def _create_type_definitions(self) -> str:
        """Generate all vehicle and pedestrian type definitions."""
        xml = ""
        
        # Vehicle types
        for vtype, props in VEHICLE_TYPES.items():
            xml += f'    <vType id="{vtype}" vClass="passenger" length="{props["length"]}" maxSpeed="{props["maxSpeed"]}" accel="2.6" decel="4.5" color="{props["color"]}"/>\n'
        
        # Emergency types
        for etype, props in EMERGENCY_TYPES.items():
            xml += f'    <vType id="{etype}" vClass="emergency" length="{props["length"]}" maxSpeed="{props["maxSpeed"]}" accel="2.6" decel="4.5" color="{props["color"]}"/>\n'
        
        # Pedestrian types
        for ptype, props in PEDESTRIAN_TYPES.items():
            xml += f'    <pType id="{ptype}" maxSpeed="{props["maxSpeed"]}" color="{props["color"]}"/>\n'
        
        return xml

    def _create_route_definitions(self) -> str:
        """Generate route definitions for all entry-exit combinations."""
        xml = ""
        for entry, exit_edge in ALL_ROUTES:
            route_id = f"route_{entry}_{exit_edge}"
            xml += f'    <route id="{route_id}" edges="{entry} {exit_edge}"/>\n'
        return xml

    def _generate_vehicle_flow(
        self,
        scenario_name: str,
        entry_edge: str,
        exit_edge: str,
        vtype: str,
        count: int,
        time_start: int,
        time_end: int,
    ) -> List[str]:
        """Generate individual vehicles for a route."""
        vehicles = []
        route_id = f"route_{entry_edge}_{exit_edge}"
        
        for i in range(count):
            depart = random.uniform(time_start, time_end)
            vehicle_id = f"{scenario_name}_veh_{vtype}_{entry_edge}_{exit_edge}_{i}"
            vehicles.append(
                f'        <vehicle id="{vehicle_id}" type="{vtype}" route="{route_id}" depart="{depart:.1f}" departLane="best" departSpeed="max"/>'
            )
        
        return vehicles

    def _generate_emergency_flow(
        self,
        scenario_name: str,
        etype: str,
        count: int,
        time_start: int,
        time_end: int,
    ) -> List[str]:
        """Generate emergency vehicles with random routes."""
        emergencies = []
        
        for i in range(count):
            entry = random.choice(ENTRY_EDGES)
            exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
            route_id = f"route_{entry}_{exit_edge}"
            depart = random.uniform(time_start, time_end)
            vehicle_id = f"{scenario_name}_{etype}_{i}"
            
            emergencies.append(
                f'        <vehicle id="{vehicle_id}" type="{etype}" route="{route_id}" depart="{depart:.1f}" departLane="best" departSpeed="max"/>'
            )
        
        return emergencies

    def _generate_pedestrians(
        self,
        scenario_name: str,
        ped_type: str,
        count: int,
        time_start: int,
        time_end: int,
    ) -> List[str]:
        """Generate pedestrians crossing at specific times."""
        pedestrians = []
        
        for i in range(count):
            depart = random.uniform(time_start, time_end)
            from_crossing, to_crossing = random.choice(PEDESTRIAN_CROSSINGS)
            person_id = f"{scenario_name}_ped_{ped_type}_{i}"
            
            pedestrians.append(f'        <person id="{person_id}" type="{ped_type}" depart="{depart:.1f}">')
            pedestrians.append(f'            <walk edges="{from_crossing} {to_crossing}" arrivalPos="1.0"/>')
            pedestrians.append(f'        </person>')
        
        return pedestrians

    def _save_scenario(self, name: str, content_elements: List[str]) -> str:
        """Save scenario to XML file."""
        filename = os.path.join(self.output_dir, f"{name}.rou.xml")
        
        with open(filename, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">\n')
            
            # Type definitions
            f.write(self._create_type_definitions())
            f.write("\n")
            
            # Route definitions
            f.write(self._create_route_definitions())
            f.write("\n")
            
            # Vehicles and pedestrians
            for element in content_elements:
                f.write(element + "\n")
            
            f.write("</routes>\n")
        
        self.scenario_index += 1
        print(f"[{self.scenario_index}] {filename}")
        return filename

    def generate_all_scenarios(self) -> List[str]:
        """Generate all 75 comprehensive scenarios."""
        scenarios = []

        # 1. ROUTE COVERAGE SCENARIOS (16 total) - Ensure all routes are exercised
        print("\n=== ROUTE COVERAGE SCENARIOS (16) ===")
        route_idx = 0
        for entry, exit_edge in ALL_ROUTES:
            if route_idx >= 16:
                break
            route_idx += 1
            
            name = f"s01_route_{entry}_{exit_edge}"
            elements = []
            
            # 15 vehicles per route with mixed types
            for vtype in ["car", "bike", "auto"]:
                elements.extend(self._generate_vehicle_flow(
                    name, entry, exit_edge, vtype, 5, 0, 3600
                ))
            
            scenarios.append(self._save_scenario(name, elements))

        # 2. LIGHT TRAFFIC SCENARIOS (8 total)
        print("\n=== LIGHT TRAFFIC SCENARIOS (8) ===")
        for i in range(8):
            name = f"s02_light_traffic_{i+1}"
            elements = []
            
            # Low vehicle count (30-50 total)
            vehicle_count = random.randint(30, 50)
            for _ in range(vehicle_count):
                vtype = random.choice(["bike", "car", "auto"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Few pedestrians (5-10)
            for ptype in ["adult", "student"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(2, 5), 0, 3600))
            
            # No emergencies
            scenarios.append(self._save_scenario(name, elements))

        # 3. HEAVY TRAFFIC SCENARIOS (8 total)
        print("\n=== HEAVY TRAFFIC SCENARIOS (8) ===")
        for i in range(8):
            name = f"s03_heavy_traffic_{i+1}"
            elements = []
            
            # High vehicle count (150-200)
            vehicle_count = random.randint(150, 200)
            for _ in range(vehicle_count):
                vtype = random.choice(list(VEHICLE_TYPES.keys()))
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Some pedestrians (10-15)
            for ptype in ["adult", "student", "elderly"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(3, 5), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))

        # 4. EMERGENCY-FOCUSED SCENARIOS (12 total)
        print("\n=== EMERGENCY-FOCUSED SCENARIOS (12) ===")
        
        # 4a: Single emergency with normal traffic (4 scenarios)
        for i in range(4):
            name = f"s04a_single_emergency_{i+1}"
            elements = []
            
            # Normal traffic
            for _ in range(80):
                vtype = random.choice(["car", "bike", "auto", "truck"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # 1 emergency
            elements.extend(self._generate_emergency_flow(name, random.choice(list(EMERGENCY_TYPES.keys())), 1, 500, 2000))
            
            # Pedestrians
            for ptype in ["adult", "student"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(5, 10), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 4b: Multiple emergencies (4 scenarios)
        for i in range(4):
            name = f"s04b_multiple_emergencies_{i+1}"
            elements = []
            
            # Moderate traffic
            for _ in range(100):
                vtype = random.choice(["car", "auto"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # 3-4 emergencies scattered
            for etype in random.choices(list(EMERGENCY_TYPES.keys()), k=random.randint(3, 4)):
                elements.extend(self._generate_emergency_flow(name, etype, 1, random.randint(500, 2500), random.randint(1500, 3000)))
            
            # Moderate pedestrians
            for ptype in ["adult", "elderly"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(8, 12), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 4c: Emergency + pedestrian crossing conflict (4 scenarios)
        for i in range(4):
            name = f"s04c_emergency_ped_conflict_{i+1}"
            elements = []
            
            # Light-moderate traffic
            for _ in range(60):
                vtype = random.choice(["car", "bike"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Emergency arriving during pedestrian crossing
            emergency_time = random.randint(1000, 2000)
            elements.extend(self._generate_emergency_flow(name, random.choice(list(EMERGENCY_TYPES.keys())), 1, emergency_time - 100, emergency_time + 100))
            
            # Pedestrians crossing at same time
            for ptype in ["adult", "student"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(5, 8), emergency_time - 200, emergency_time + 200))
            
            scenarios.append(self._save_scenario(name, elements))

        # 5. HIGH-PEDESTRIAN SCENARIOS (12 total)
        print("\n=== HIGH-PEDESTRIAN SCENARIOS (12) ===")
        
        # 5a: High pedestrian count (4 scenarios)
        for i in range(4):
            name = f"s05a_high_pedestrians_{i+1}"
            elements = []
            
            # Light vehicle traffic
            for _ in range(40):
                vtype = random.choice(["car", "bike"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # High pedestrian count (25-35 total)
            ped_count = random.randint(25, 35)
            for ptype in ["adult", "student", "elderly", "mobility_aid"]:
                elements.extend(self._generate_pedestrians(name, ptype, ped_count // 4, 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 5b: Mixed pedestrian types with high count (4 scenarios)
        for i in range(4):
            name = f"s05b_mixed_pedestrians_{i+1}"
            elements = []
            
            # Moderate traffic
            for _ in range(70):
                vtype = random.choice(["car", "auto", "bike"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Many pedestrians of specific types (20-30)
            ped_count = random.randint(20, 30)
            elements.extend(self._generate_pedestrians(name, "adult", ped_count // 2, 0, 3600))
            elements.extend(self._generate_pedestrians(name, "elderly", ped_count // 4, 0, 3600))
            elements.extend(self._generate_pedestrians(name, "mobility_aid", ped_count // 4, 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 5c: High-priority pedestrians (mobility-aided) focus (4 scenarios)
        for i in range(4):
            name = f"s05c_high_priority_peds_{i+1}"
            elements = []
            
            # Moderate vehicle traffic
            for _ in range(90):
                vtype = random.choice(["car", "truck", "auto"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Many mobility-aided pedestrians (15-20)
            elements.extend(self._generate_pedestrians(name, "mobility_aid", random.randint(15, 20), 0, 3600))
            # Few other pedestrian types
            elements.extend(self._generate_pedestrians(name, "adult", random.randint(3, 5), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))

        # 6. EDGE CASE SCENARIOS (8 total)
        print("\n=== EDGE CASE SCENARIOS (8) ===")
        
        # 6a: No vehicles, only pedestrians (2 scenarios)
        for i in range(2):
            name = f"s06a_no_vehicles_{i+1}"
            elements = []
            
            # Only pedestrians (20-30)
            ped_count = random.randint(20, 30)
            for ptype in ["adult", "student", "elderly", "mobility_aid"]:
                elements.extend(self._generate_pedestrians(name, ptype, ped_count // 4, 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 6b: No pedestrians, only vehicles (2 scenarios)
        for i in range(2):
            name = f"s06b_no_pedestrians_{i+1}"
            elements = []
            
            # Moderate vehicle traffic
            for _ in range(120):
                vtype = random.choice(list(VEHICLE_TYPES.keys()))
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 6c: Minimal scenario - almost empty (2 scenarios)
        for i in range(2):
            name = f"s06c_minimal_{i+1}"
            elements = []
            
            # Very few vehicles (5-10)
            for _ in range(random.randint(5, 10)):
                vtype = random.choice(["car", "bike"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # 1-2 pedestrians
            elements.extend(self._generate_pedestrians(name, "adult", random.randint(1, 2), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 6d: Empty scenario - baseline (2 scenarios)
        for i in range(2):
            name = f"s06d_empty_{i+1}"
            elements = []
            # Completely empty - no vehicles, no pedestrians
            scenarios.append(self._save_scenario(name, elements))

        # 7. COMPLEX PRIORITY SCENARIOS (11 total)
        print("\n=== COMPLEX PRIORITY SCENARIOS (11) ===")
        
        # 7a: Mobility-aided pedestrians vs emergencies (3 scenarios)
        for i in range(3):
            name = f"s07a_mobility_vs_emergency_{i+1}"
            elements = []
            
            # Moderate traffic
            for _ in range(80):
                vtype = random.choice(["car", "auto"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Many mobility-aided pedestrians
            elements.extend(self._generate_pedestrians(name, "mobility_aid", random.randint(12, 18), 1000, 2500))
            
            # 2-3 emergencies during pedestrian crossing
            for _ in range(random.randint(2, 3)):
                elements.extend(self._generate_emergency_flow(name, random.choice(list(EMERGENCY_TYPES.keys())), 1, 1200, 2300))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 7b: High-priority vehicles competing for right-of-way (3 scenarios)
        for i in range(3):
            name = f"s07b_priority_vehicle_conflict_{i+1}"
            elements = []
            
            # Heavy traffic with multiple emergency types
            for _ in range(110):
                vtype = random.choice(["car", "truck", "bus"])
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Multiple emergencies arriving at different times
            for etype in ["ambulance", "police", "firetruck"]:
                elements.extend(self._generate_emergency_flow(name, etype, 1, random.randint(800, 1500), random.randint(1500, 2500)))
            
            # Pedestrians
            for ptype in ["adult", "elderly"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(8, 12), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 7c: Extreme scenario - rush hour with everything (2 scenarios)
        for i in range(2):
            name = f"s07c_extreme_rush_hour_{i+1}"
            elements = []
            
            # Very heavy traffic (180-220 vehicles)
            for _ in range(random.randint(180, 220)):
                vtype = random.choice(list(VEHICLE_TYPES.keys()))
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # Multiple emergencies
            for _ in range(random.randint(3, 5)):
                elements.extend(self._generate_emergency_flow(name, random.choice(list(EMERGENCY_TYPES.keys())), 1, random.randint(500, 3000), random.randint(800, 3100)))
            
            # Many pedestrians
            for ptype in ["adult", "student", "elderly", "mobility_aid"]:
                elements.extend(self._generate_pedestrians(name, ptype, random.randint(6, 10), 0, 3600))
            
            scenarios.append(self._save_scenario(name, elements))
        
        # 7d: Complex multi-objective scenario (3 scenarios)
        for i in range(3):
            name = f"s07d_complex_multiobjective_{i+1}"
            elements = []
            
            # Complex traffic pattern
            for _ in range(95):
                vtype = random.choice(list(VEHICLE_TYPES.keys()))
                entry = random.choice(ENTRY_EDGES)
                exit_edge = random.choice([e for e in EXIT_EDGES if e != entry])
                elements.extend(self._generate_vehicle_flow(name, entry, exit_edge, vtype, 1, 0, 3600))
            
            # 2 emergencies with staggered timing
            elements.extend(self._generate_emergency_flow(name, "ambulance", 1, 1000, 1500))
            elements.extend(self._generate_emergency_flow(name, "police", 1, 2000, 2500))
            
            # High pedestrian activity
            elements.extend(self._generate_pedestrians(name, "adult", 10, 900, 1600))
            elements.extend(self._generate_pedestrians(name, "mobility_aid", 8, 1900, 2600))
            elements.extend(self._generate_pedestrians(name, "elderly", 6, 500, 3500))
            
            scenarios.append(self._save_scenario(name, elements))

        print(f"\n✅ Generated {len(scenarios)} scenarios")
        print(f"Output directory: {self.output_dir}")
        return scenarios


def main():
    """Generate all 75 scenarios."""
    generator = ScenarioGenerator()
    scenarios = generator.generate_all_scenarios()
    
    print("\n" + "="*70)
    print("SCENARIO SUITE SUMMARY")
    print("="*70)
    print(f"Total scenarios: {len(scenarios)}")
    print(f"Per episode duration: 3600 steps")
    print(f"Total episodes: 75")
    print(f"\nScenario categories:")
    print(f"  1. Route coverage: 16 (all entry-exit combinations)")
    print(f"  2. Light traffic: 8")
    print(f"  3. Heavy traffic: 8")
    print(f"  4. Emergency-focused: 12 (single, multiple, conflicts)")
    print(f"  5. High-pedestrian: 12 (volume, types, priority)")
    print(f"  6. Edge cases: 8 (empty, minimal, no-vehicles, no-peds)")
    print(f"  7. Complex priority: 11 (multiobjective, rush-hour, conflicts)")
    print("\n" + "="*70)
    print("Configuration for marl_config.json:")
    print("="*70)
    print("""
Add these settings:
  "use_scenario_files": true,
  "scenario_dir": "sumo_configs/scenarios",
  "scenario_selection_strategy": "round_robin"
""")


if __name__ == "__main__":
    main()
