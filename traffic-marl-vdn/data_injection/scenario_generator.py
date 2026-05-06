"""Generate SUMO scenario route files from the original working 3junctions route template.

The original route file already worked with the network, so this generator keeps the same
network and route semantics while producing 75 scenario-specific SUMO configs and route
files for training without MongoDB polling.
"""
from __future__ import annotations

import copy
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
BASE_ROUTE_FILE = BASE_DIR / "sumo_configs" / "3junctions.rou.xml"
BASE_SUMOCFG_FILE = BASE_DIR / "sumo_configs" / "3junctions.sumocfg"
OUTPUT_DIR = BASE_DIR / "sumo_configs" / "scenarios"

NORMAL_TYPES = ["bike", "car", "auto", "truck", "bus", "lorry"]
EMERGENCY_TYPES = ["ambulance", "police", "firetruck"]
PEDESTRIAN_TYPES = ["adult", "student", "elder", "mobility_aid"]

FLOW_IDS = [f"f_{idx}" for idx in range(24)]


class ScenarioGenerator:
    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not BASE_ROUTE_FILE.exists():
            raise FileNotFoundError(f"Base route file not found: {BASE_ROUTE_FILE}")
        if not BASE_SUMOCFG_FILE.exists():
            raise FileNotFoundError(f"Base SUMO config not found: {BASE_SUMOCFG_FILE}")

        self.base_route_tree = ET.parse(BASE_ROUTE_FILE)
        self.base_route_root = self.base_route_tree.getroot()
        self.base_sumocfg_tree = ET.parse(BASE_SUMOCFG_FILE)
        self.base_sumocfg_root = self.base_sumocfg_tree.getroot()

    @staticmethod
    def _find_input_node(root: ET.Element) -> ET.Element:
        node = root.find("input")
        if node is None:
            raise ValueError("SUMO config is missing an <input> section")
        return node

    @staticmethod
    def _set_route_file_in_sumocfg(root: ET.Element, route_filename: str) -> None:
        input_node = ScenarioGenerator._find_input_node(root)
        route_node = input_node.find("route-files")
        if route_node is None:
            route_node = ET.SubElement(input_node, "route-files")
        route_node.set("value", route_filename)

    @staticmethod
    def _set_net_file_in_sumocfg(root: ET.Element, net_filename: str) -> None:
        input_node = ScenarioGenerator._find_input_node(root)
        net_node = input_node.find("net-file")
        if net_node is None:
            net_node = ET.SubElement(input_node, "net-file")
        net_node.set("value", net_filename)

    @staticmethod
    def _clean_vehicle_flows(root: ET.Element) -> None:
        for flow in list(root.findall("flow")):
            root.remove(flow)

    @staticmethod
    def _clean_persons(root: ET.Element) -> None:
        """Remove all person elements (not personFlow)."""
        for person in list(root.findall("person")):
            root.remove(person)

    @staticmethod
    def _ensure_pedestrian_vtypes(root: ET.Element) -> None:
        """Ensure all pedestrian vType definitions exist."""
        existing_types = {elem.get("id") for elem in root.findall("vType")}
        ped_types = {
            "adult": ('pedestrian', '0.50', 'green'),
            "elder": ('pedestrian', '0.45', 'gray'),
            "student": ('pedestrian', '0.40', 'yellow'),
            "mobility_aid": ('pedestrian', '0.30', 'blue'),
        }
        for ped_id, (vclass, max_speed, color) in ped_types.items():
            if ped_id not in existing_types:
                vtype = ET.Element("vType", {
                    "id": ped_id,
                    "vClass": vclass,
                    "maxSpeed": max_speed,
                    "color": color,
                })
                root.insert(len(list(root.findall("vType"))), vtype)

    @staticmethod
    def _add_person_chunk(root: ET.Element, chunk_id: str, person_type: str, from_edge: str, 
                          chunk_size: int, start_time: int, spacing: float = 1.0) -> None:
        """Add a chunk of individual pedestrians (not personFlow) at a pedestrian crossing."""
        to_edge = "-E0.80" if from_edge in {"E00", "E0"} else "E00"
        
        for i in range(chunk_size):
            person_id = f"{chunk_id}_p{i}"
            depart_time = start_time + (i * spacing)
            
            person = ET.Element("person", {
                "id": person_id,
                "type": person_type,
                "depart": f"{depart_time:.2f}",
            })
            personTrip = ET.SubElement(person, "personTrip")
            personTrip.set("from", from_edge)
            personTrip.set("to", to_edge)
            
            root.append(person)

    @staticmethod
    def _add_emergency_flows(root: ET.Element, entries: Sequence[Tuple[str, str, int, int, float]]) -> None:
        flows = root.findall("flow")
        if not flows:
            return
        for flow_id, emergency_type, begin, end, vehs_per_hour in entries:
            template_flow = random.choice(flows)
            new_flow = copy.deepcopy(template_flow)
            new_flow.set("id", flow_id)
            new_flow.set("type", emergency_type)
            new_flow.set("begin", f"{begin:.2f}")
            new_flow.set("end", f"{end:.2f}")
            new_flow.set("vehsPerHour", f"{vehs_per_hour:.2f}")
            root.append(new_flow)

    @staticmethod
    def _random_type_pattern(weights: Dict[str, int]) -> List[str]:
        pattern: List[str] = []
        for vehicle_type, count in weights.items():
            pattern.extend([vehicle_type] * count)
        random.shuffle(pattern)
        return pattern

    @staticmethod
    def _scale_base_flows(
        root: ET.Element,
        flow_scale: float,
        min_vph: int,
        max_vph: int,
        type_pattern: Sequence[str],
        emphasize_flow_id: Optional[str] = None,
        emphasize_vph: Optional[int] = None,
        window_count_range: Tuple[int, int] = (6, 14),
        force_bursty: bool = True,
    ) -> None:
        flows = [copy.deepcopy(flow) for flow in root.findall("flow")]
        if not flows:
            return

        # Replace static full-episode flows with short burst windows so demand varies
        # across time and lanes within one episode.
        for flow in list(root.findall("flow")):
            root.remove(flow)

        for index, flow in enumerate(flows):
            base_id = flow.get("id", f"f_{index}")
            base_vph = int(float(flow.get("vehsPerHour", "20")))
            scaled_vph = max(min_vph, min(max_vph, int(round(base_vph * flow_scale))))
            if emphasize_flow_id and base_id == emphasize_flow_id and emphasize_vph is not None:
                scaled_vph = emphasize_vph

            n_windows = random.randint(window_count_range[0], window_count_range[1])
            for w in range(n_windows):
                start = random.randint(0, 3300)
                duration = random.randint(120, 780) if force_bursty else random.randint(300, 1200)
                end = min(3600, start + duration)
                if end <= start:
                    continue

                burst = random.uniform(0.7, 2.5)
                if random.random() < 0.25:
                    burst *= random.uniform(1.5, 3.5)

                vph = max(min_vph, min(max_vph, int(round(scaled_vph * burst))))
                new_flow = copy.deepcopy(flow)
                new_flow.set("id", f"{base_id}_w{w}_{random.randint(100, 999)}")
                new_flow.set("begin", f"{start:.2f}")
                new_flow.set("end", f"{end:.2f}")
                new_flow.set("vehsPerHour", str(vph))
                new_flow.set("type", random.choice(type_pattern))
                root.append(new_flow)

    @staticmethod
    def _write_xml(tree: ET.ElementTree, path: Path) -> None:
        try:
            ET.indent(tree, space="    ")
        except Exception:
            pass
        tree.write(path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _sort_departure_items(route_root: ET.Element) -> None:
        """Sort flows/personFlows/persons by begin/depart time so SUMO does not ignore unsorted demand."""
        flow_items = [elem for elem in route_root if elem.tag in {"flow", "personFlow", "person"}]
        if not flow_items:
            return

        for elem in flow_items:
            route_root.remove(elem)

        # Sort by begin (for flow/personFlow) or depart (for person)
        def get_start_time(elem):
            if elem.tag == "person":
                return float(elem.get("depart", "0") or 0.0)
            else:
                return float(elem.get("begin", "0") or 0.0)
        
        flow_items.sort(key=get_start_time)
        for elem in flow_items:
            route_root.append(elem)

    def _base_scenario(self) -> Tuple[ET.Element, ET.Element]:
        return copy.deepcopy(self.base_route_root), copy.deepcopy(self.base_sumocfg_root)

    def _save_scenario(self, scenario_name: str, route_root: ET.Element, sumocfg_root: ET.Element) -> Path:
        route_path = self.output_dir / f"{scenario_name}.rou.xml"
        sumocfg_path = self.output_dir / f"{scenario_name}.sumocfg"

        sumocfg_tree = ET.ElementTree(copy.deepcopy(sumocfg_root))
        self._set_route_file_in_sumocfg(sumocfg_tree.getroot(), route_path.name)
        self._set_net_file_in_sumocfg(sumocfg_tree.getroot(), "../3junctions.net.xml")
        input_node = self._find_input_node(sumocfg_tree.getroot())
        gui_node = sumocfg_tree.getroot().find("gui_only/gui-settings-file")
        if gui_node is not None:
            gui_node.set("value", "../gui-settings.xml")

        self._sort_departure_items(route_root)

        self._write_xml(ET.ElementTree(copy.deepcopy(route_root)), route_path)
        self._write_xml(sumocfg_tree, sumocfg_path)
        return route_path

    def _scenario_route_coverage(self, target_flow_id: str) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern(
            {"car": 4, "auto": 3, "bike": 2, "truck": 2, "bus": 1, "lorry": 1}
        )
        self._scale_base_flows(
            route_root,
            flow_scale=2.0,
            min_vph=15,
            max_vph=120,
            type_pattern=pattern,
            emphasize_flow_id=target_flow_id,
            emphasize_vph=220,
            window_count_range=(8, 16),
        )
        self._clean_persons(route_root)
        # Add pedestrian chunks at crossings
        for idx in range(random.randint(4, 8)):
            chunk_size = random.randint(3, 8)
            ped_type = random.choice(["adult", "student", "elder", "mobility_aid"])
            from_edge = random.choice(["E00", "-E0.80", "E0"])
            start_time = random.randint(100, 3200)
            self._add_person_chunk(route_root, f"chunk_rc_{target_flow_id}_{idx}", ped_type, from_edge, chunk_size, start_time, spacing=1.5)
        return route_root, sumocfg_root

    def _scenario_light_traffic(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"bike": 3, "car": 4, "auto": 2, "truck": 1})
        self._scale_base_flows(route_root, flow_scale=1.2, min_vph=5, max_vph=40, type_pattern=pattern, window_count_range=(4, 9))
        self._clean_persons(route_root)
        if random.random() < 0.8:
            for idx in range(random.randint(2, 4)):
                chunk_size = random.randint(2, 5)
                ped_type = random.choice(["adult", "student", "elder", "mobility_aid"])
                from_edge = random.choice(["E00", "-E0.80"])
                start_time = random.randint(200, 3200)
                self._add_person_chunk(route_root, f"chunk_light_{idx}", ped_type, from_edge, chunk_size, start_time, spacing=1.2)
        return route_root, sumocfg_root

    def _scenario_heavy_traffic(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 5, "truck": 2, "bus": 2, "lorry": 2, "auto": 1, "bike": 1})
        self._scale_base_flows(route_root, flow_scale=16.0, min_vph=60, max_vph=650, type_pattern=pattern, window_count_range=(10, 20))
        self._clean_persons(route_root)
        for idx in range(random.randint(6, 10)):
            chunk_size = random.randint(4, 10)
            ped_type = random.choice(["adult", "student", "elder", "mobility_aid"])
            from_edge = random.choice(["E00", "-E0.80", "E0"])
            start_time = random.randint(300, 3200)
            self._add_person_chunk(route_root, f"chunk_heavy_{idx}", ped_type, from_edge, chunk_size, start_time, spacing=1.5)
        return route_root, sumocfg_root

    def _scenario_single_emergency(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 4, "bike": 2, "auto": 2, "truck": 1})
        self._scale_base_flows(route_root, flow_scale=5.0, min_vph=25, max_vph=200, type_pattern=pattern, window_count_range=(8, 14))
        self._add_emergency_flows(
            route_root,
            [
                (
                    f"emg_single_{random.randint(1000, 9999)}",
                    random.choice(EMERGENCY_TYPES),
                    random.randint(900, 1500),
                    random.randint(1501, 2600),
                    random.uniform(80, 200),
                )
                for _ in range(random.randint(1, 2))
            ],
        )
        self._clean_persons(route_root)
        # High pedestrian chunks near emergency vehicle time
        self._add_person_chunk(route_root, "ped_emergency_1", "mobility_aid", "E00", random.randint(8, 12), 900, 1.5)
        self._add_person_chunk(route_root, "ped_emergency_2", "adult", "-E0.80", random.randint(6, 10), 1000, 1.5)
        self._add_person_chunk(route_root, "ped_emergency_3", "elder", "E0", random.randint(5, 8), 1000, 1.5)
        return route_root, sumocfg_root

    def _scenario_multiple_emergencies(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 3, "truck": 2, "bus": 2, "auto": 2, "bike": 1, "lorry": 1})
        self._scale_base_flows(route_root, flow_scale=6.5, min_vph=30, max_vph=250, type_pattern=pattern, window_count_range=(8, 16))
        emergency_entries = [
            (
                f"emg_multi_{idx}_{random.randint(1000, 9999)}",
                random.choice(EMERGENCY_TYPES),
                random.randint(400, 2600),
                random.randint(2201, 3500),
                random.uniform(100, 220),
            )
            for idx in range(random.randint(12, 20))
        ]
        self._add_emergency_flows(route_root, emergency_entries)
        self._clean_persons(route_root)
        for idx in range(random.randint(8, 12)):
            chunk_size = random.randint(6, 15)
            ped_type = random.choice(["adult", "elder", "student", "mobility_aid"])
            from_edge = random.choice(["E00", "-E0.80", "E0"])
            start_time = random.randint(400, 3200)
            self._add_person_chunk(route_root, f"chunk_multi_emg_{idx}", ped_type, from_edge, chunk_size, start_time, spacing=1.2)
        return route_root, sumocfg_root

    def _scenario_emergency_vs_pedestrians(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 4, "bike": 2, "auto": 2, "truck": 1})
        self._scale_base_flows(route_root, flow_scale=4.0, min_vph=20, max_vph=180, type_pattern=pattern, window_count_range=(8, 15))
        emergency_time = random.randint(1100, 2200)
        self._add_emergency_flows(
            route_root,
            [
                (
                    f"emg_ped_conflict_{random.randint(1000, 9999)}",
                    random.choice(EMERGENCY_TYPES),
                    emergency_time - 100,
                    emergency_time + 500,
                    random.uniform(120, 240),
                )
                for _ in range(random.randint(8, 16))
            ],
        )
        self._clean_persons(route_root)
        # Large pedestrian chunks crossing while emergency vehicles approach
        self._add_person_chunk(route_root, "ped_emg_cross_1", "mobility_aid", "E00", random.randint(12, 20), emergency_time - 200, 1.0)
        self._add_person_chunk(route_root, "ped_emg_cross_2", "adult", "-E0.80", random.randint(10, 18), emergency_time - 100, 1.0)
        self._add_person_chunk(route_root, "ped_emg_cross_3", "elder", "E0", random.randint(8, 14), emergency_time, 1.2)
        self._add_person_chunk(route_root, "ped_emg_cross_4", "student", "E00", random.randint(6, 12), emergency_time + 100, 1.5)
        return route_root, sumocfg_root

    def _scenario_high_pedestrians(self, mobility_heavy: bool = False) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 3, "auto": 2, "bike": 2, "truck": 1})
        self._scale_base_flows(route_root, flow_scale=5.0, min_vph=20, max_vph=180, type_pattern=pattern, window_count_range=(7, 14))
        self._clean_persons(route_root)
        
        if mobility_heavy:
            # Many mobility aid users (priority scenario)
            for idx in range(random.randint(12, 18)):
                chunk_size = random.randint(5, 12)
                self._add_person_chunk(route_root, f"chunk_mob_{idx}", "mobility_aid", 
                                     random.choice(["E00", "-E0.80"]), chunk_size, 
                                     random.randint(600, 3000), spacing=1.0)
            for idx in range(random.randint(8, 12)):
                chunk_size = random.randint(3, 8)
                ped_type = random.choice(["adult", "elder", "student"])
                self._add_person_chunk(route_root, f"chunk_other_{idx}", ped_type,
                                     random.choice(["E00", "-E0.80"]), chunk_size,
                                     random.randint(500, 3200), spacing=1.2)
        else:
            # General high pedestrian traffic
            for idx in range(random.randint(14, 22)):
                chunk_size = random.randint(4, 10)
                ped_type = random.choice(["adult", "student", "elder", "mobility_aid"])
                from_edge = random.choice(["E00", "-E0.80", "E0"])
                self._add_person_chunk(route_root, f"chunk_high_{idx}", ped_type,
                                     from_edge, chunk_size, random.randint(200, 3300), spacing=1.0)
        return route_root, sumocfg_root

    def _scenario_no_vehicles(self, with_pedestrians: bool = True) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        self._clean_vehicle_flows(route_root)
        self._clean_persons(route_root)
        if with_pedestrians:
            for idx in range(random.randint(8, 14)):
                chunk_size = random.randint(4, 10)
                ped_type = random.choice(["adult", "student", "elder", "mobility_aid"])
                from_edge = random.choice(["E00", "-E0.80", "E0"])
                start_time = random.randint(300, 3300)
                self._add_person_chunk(route_root, f"chunk_noveh_{idx}", ped_type, from_edge, chunk_size, start_time, spacing=1.5)
        return route_root, sumocfg_root

    def _scenario_no_pedestrians(self, empty: bool = False) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        self._clean_persons(route_root)
        if empty:
            self._clean_vehicle_flows(route_root)
        else:
            pattern = self._random_type_pattern({"car": 4, "truck": 2, "bus": 1, "auto": 2, "bike": 1})
            self._scale_base_flows(route_root, flow_scale=8.0, min_vph=40, max_vph=320, type_pattern=pattern, window_count_range=(9, 16))
        return route_root, sumocfg_root

    def _scenario_minimal(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"bike": 2, "car": 3, "auto": 1})
        self._scale_base_flows(route_root, flow_scale=0.6, min_vph=3, max_vph=20, type_pattern=pattern, window_count_range=(2, 4))
        self._clean_persons(route_root)
        self._add_person_chunk(route_root, "chunk_minimal", "adult", "E00", random.randint(2, 5), 500, 2.0)
        return route_root, sumocfg_root

    def _scenario_priority_stress(self) -> Tuple[ET.Element, ET.Element]:
        route_root, sumocfg_root = self._base_scenario()
        self._ensure_pedestrian_vtypes(route_root)
        pattern = self._random_type_pattern({"car": 3, "truck": 2, "bus": 2, "lorry": 2, "auto": 1})
        self._scale_base_flows(route_root, flow_scale=8.5, min_vph=50, max_vph=420, type_pattern=pattern, window_count_range=(10, 18))
        self._clean_persons(route_root)
        
        # Heavy mobility_aid pedestrian chunks (high priority)
        for idx in range(random.randint(14, 22)):
            chunk_size = random.randint(8, 18)
            self._add_person_chunk(route_root, f"chunk_priority_mob_{idx}", "mobility_aid",
                                 random.choice(["E00", "-E0.80"]), chunk_size,
                                 random.randint(700, 3300), spacing=0.8)
        
        # Heavy emergency vehicle presence
        emergency_entries = [
            (
                f"emg_priority_{idx}_{random.randint(1000, 9999)}",
                random.choice(EMERGENCY_TYPES),
                random.randint(600, 2800),
                random.randint(1400, 3500),
                random.uniform(200, 400),
            )
            for idx in range(random.randint(24, 40))
        ]
        self._add_emergency_flows(route_root, emergency_entries)
        
        # Additional normal pedestrians
        for idx in range(random.randint(10, 16)):
            chunk_size = random.randint(4, 10)
            ped_type = random.choice(["adult", "elder", "student"])
            self._add_person_chunk(route_root, f"chunk_priority_other_{idx}", ped_type,
                                 random.choice(["E00", "-E0.80", "E0"]), chunk_size,
                                 random.randint(300, 3200), spacing=1.2)
        return route_root, sumocfg_root

    def generate_scenarios(self) -> List[Path]:
        generated: List[Path] = []

        for idx, flow_id in enumerate(FLOW_IDS):
            route_root, sumocfg_root = self._scenario_route_coverage(flow_id)
            generated.append(self._save_scenario(f"s01_route_coverage_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(8):
            route_root, sumocfg_root = self._scenario_light_traffic()
            generated.append(self._save_scenario(f"s02_light_traffic_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(8):
            route_root, sumocfg_root = self._scenario_heavy_traffic()
            generated.append(self._save_scenario(f"s03_heavy_traffic_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(4):
            route_root, sumocfg_root = self._scenario_single_emergency()
            generated.append(self._save_scenario(f"s04a_single_emergency_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(4):
            route_root, sumocfg_root = self._scenario_multiple_emergencies()
            generated.append(self._save_scenario(f"s04b_multiple_emergencies_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(4):
            route_root, sumocfg_root = self._scenario_emergency_vs_pedestrians()
            generated.append(self._save_scenario(f"s04c_emergency_ped_conflict_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(4):
            route_root, sumocfg_root = self._scenario_high_pedestrians(mobility_heavy=False)
            generated.append(self._save_scenario(f"s05a_high_pedestrians_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(4):
            route_root, sumocfg_root = self._scenario_high_pedestrians(mobility_heavy=True)
            generated.append(self._save_scenario(f"s05b_mobility_priority_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(2):
            route_root, sumocfg_root = self._scenario_no_vehicles(with_pedestrians=True)
            generated.append(self._save_scenario(f"s06a_no_vehicles_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(2):
            route_root, sumocfg_root = self._scenario_no_pedestrians(empty=False)
            generated.append(self._save_scenario(f"s06b_no_pedestrians_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(2):
            route_root, sumocfg_root = self._scenario_minimal()
            generated.append(self._save_scenario(f"s06c_minimal_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(2):
            route_root, sumocfg_root = self._scenario_no_vehicles(with_pedestrians=False)
            generated.append(self._save_scenario(f"s06d_empty_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(3):
            route_root, sumocfg_root = self._scenario_priority_stress()
            generated.append(self._save_scenario(f"s07a_priority_stress_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(3):
            route_root, sumocfg_root = self._scenario_multiple_emergencies()
            generated.append(self._save_scenario(f"s07b_priority_vehicle_conflict_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(2):
            route_root, sumocfg_root = self._scenario_emergency_vs_pedestrians()
            generated.append(self._save_scenario(f"s07c_extreme_crossing_{idx + 1:02d}", route_root, sumocfg_root))

        for idx in range(3):
            route_root, sumocfg_root = self._scenario_heavy_traffic()
            generated.append(self._save_scenario(f"s07d_complex_multiobjective_{idx + 1:02d}", route_root, sumocfg_root))

        return generated


def main() -> None:
    generator = ScenarioGenerator()
    scenarios = generator.generate_scenarios()
    print(f"Generated {len(scenarios)} scenario route files and matching SUMO configs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
