"""
Factory for creating SUMO vehicles and pedestrians from MongoDB data.
Handles different types with appropriate colors and properties.
"""
import traci
import random
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

class SUMOVehicleFactory:
    """Creates SUMO vehicles and pedestrians from injection data"""
    
    # Vehicle type mappings (must match IDs already defined in 3junctions.rou.xml)
    EMER_VEHICLE_TYPES = {
        # Emergency vehicles
        'ambulance': {
            'vType': 'ambulance',
        },
        'police': {
            'vType': 'police',
        },
        'firetruck': {
            'vType': 'firetruck',
        },
    }
    
    # Pedestrian type mappings (must match IDs already defined in 3junctions.rou.xml)
    PEDESTRIAN_TYPES = {
        'elderly': {
            'vType': 'elder',
        },
        'adult': {
            'vType': 'adult',
        },
        'student': {
            'vType': 'student',
        },
        'mobility_aid': {
            'vType': 'mobility_aid',
        }
    }

    # Injected normal vehicle types mapped directly to route-file vType IDs.
    NORM_VEHICLE_TYPES = {
        'bike': {
            'vType': 'bike',
        },
        'car': {
            'vType': 'real_car',
        },
        'auto': {
            'vType': 'auto',
        },
        'bus': {
            'vType': 'bus',
        },
        'truck': {
            'vType': 'truck',
        },
        'lorry': {
            'vType': 'lorry',
        },
    }
    
    def __init__(self):
        self.types_registered = False
        self._route_counter = 0
    
    def _timestamp_to_int(self, raw_timestamp: Any) -> int:
        """Convert numeric/ISO timestamp to integer seconds for stable IDs."""
        try:
            if isinstance(raw_timestamp, (int, float)):
                return int(float(raw_timestamp))

            if isinstance(raw_timestamp, str):
                ts = raw_timestamp.strip()
                try:
                    return int(float(ts))
                except ValueError:
                    pass

                if '+' in ts:
                    dt_str = ts.split('+')[0]
                    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%f")
                    return int(dt.timestamp())

                if ts.endswith('Z'):
                    dt = datetime.strptime(ts[:-1], "%Y-%m-%dT%H:%M:%S.%f")
                    return int(dt.timestamp())

            logger.warning(f"Unsupported timestamp format for ID generation: {raw_timestamp}")
            return int(time.time())

        except Exception as e:
            logger.error(f"Error converting timestamp '{raw_timestamp}': {e}")
            return int(time.time())

    def _normalize_vehicle_type(self, vehicle_type: str) -> str:
        """Normalize teammate variants to canonical emergency type IDs."""
        normalized = vehicle_type.strip().lower()
        aliases = {
            'fire_truck': 'firetruck',
            'fire-truck': 'firetruck',
            'fire engine': 'firetruck',
        }
        return aliases.get(normalized, normalized)

    def _normalize_normal_vehicle_type(self, vehicle_type: str) -> Optional[str]:
        """Normalize teammate variants to supported injected normal vehicle types."""
        normalized = vehicle_type.strip().lower()
        aliases = {
            'motorbike': 'bike',
            'motorcycle': 'bike',
            'van': 'truck',
            'lorry_truck': 'lorry',
            'threewheeler': 'auto',
            'three_wheeler': 'auto',
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in self.NORM_VEHICLE_TYPES:
            return normalized
        return None

    def _ensure_NORM_VEHICLE_TYPES_registered(self):
        """Validate normal injected vTypes exist in loaded route-file definitions."""
        existing_types = set(traci.vehicletype.getIDList())
        missing = [cfg['vType'] for cfg in self.NORM_VEHICLE_TYPES.values() if cfg['vType'] not in existing_types]
        if missing:
            logger.warning(
                "Missing normal injected vType IDs in active SUMO scenario: %s",
                sorted(set(missing)),
            )

    def _normalize_entry_edge(self, entry_edge: str) -> str:
        """Normalize teammate entry labels to inbound network edges."""
        normalized = entry_edge.strip()
        edge_aliases = {
            # Teammate payload uses -E0 for west inbound; network inbound is E0.
            '-E0': 'E0',
        }
        return edge_aliases.get(normalized, normalized)

    def _create_runtime_route(self, from_edge: str, candidate_destinations: List[str]) -> Optional[str]:
        """Build a valid route dynamically from an entry edge to a reachable destination."""
        for to_edge in candidate_destinations:
            if to_edge == from_edge:
                continue
            try:
                route_result = traci.simulation.findRoute(from_edge, to_edge)
                edges = list(route_result.edges)
                if not edges:
                    continue

                route_id = f"inj_route_{from_edge}_{to_edge}_{self._route_counter}"
                self._route_counter += 1
                traci.route.add(route_id, edges)
                return route_id
            except Exception:
                continue

        logger.warning(f"No valid runtime route from {from_edge} to candidates {candidate_destinations}")
        return None

    def _create_runtime_route_random(
        self,
        from_edge: str,
        candidate_destinations: List[str],
        preferred_first: Optional[str] = None,
    ) -> Optional[str]:
        """Build a route while preferring one destination and randomizing fallback order."""
        candidates = list(candidate_destinations)
        random.shuffle(candidates)

        if preferred_first and preferred_first in candidates:
            candidates.remove(preferred_first)
            candidates.insert(0, preferred_first)

        return self._create_runtime_route(from_edge, candidates)

    def _get_destination_candidates(self, entry_point: str) -> List[str]:
        """Return reachable destination preference list for each entry edge."""
        destination_map = {
            'E0': ['E2', 'E4', 'E5', 'E8'],
            '-E2': ['-E0.80', 'E4', 'E5', 'E8'],
            '-E4': ['E2', '-E0.80', 'E5', 'E8'],
            '-E5': ['E4', 'E8', 'E2', '-E0.80'],
            '-E8': ['E5', 'E4', 'E2', '-E0'],
        }
        return destination_map.get(entry_point, ['E2', 'E4', 'E5', 'E8'])
    
    def _register_EMER_VEHICLE_TYPES(self):
        """Ensure route-file vehicle/person types are available in the loaded SUMO scenario."""
        if self.types_registered:
            return
            
        try:
            existing_types = traci.vehicletype.getIDList()

            required_types = {
                'ambulance', 'police', 'firetruck',
                'real_car', 'bike', 'auto', 'bus', 'truck', 'lorry',
                'adult', 'elder', 'student', 'mobility_aid',
            }
            missing = [type_id for type_id in required_types if type_id not in existing_types]
            if missing:
                logger.warning(
                    "Missing vType IDs in active SUMO scenario: %s. "
                    "Make sure the route file with type definitions is loaded.",
                    missing,
                )

            # Runtime injected types for normal-vehicle categories.
            self._ensure_NORM_VEHICLE_TYPES_registered()
            
            self.types_registered = True
            logger.info("Vehicle/person types validated against route file")
                    
        except Exception as e:
            logger.warning(f"Could not register vehicle types (SUMO may not be running): {e}")
    
    def create_emergency_vehicle(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Create an emergency vehicle from MongoDB record.
        Returns vehicle ID if successful, None otherwise.
        """
        try:
            # Try to register types (will succeed if SUMO is running)
            self._register_EMER_VEHICLE_TYPES()
            
            data = record.get('data', {})
            vehicle_type = self._normalize_vehicle_type(data.get('vehicle_type', ''))
            entry_point = self._normalize_entry_edge(data.get('entryPoint', ''))
            timestamp = record.get('timestamp', '')
            
            # Validate
            if vehicle_type not in ['ambulance', 'police', 'firetruck']:
                logger.warning(f"Unknown emergency vehicle type: {vehicle_type}")
                return None
            
            if not entry_point:
                logger.warning("No entry point specified for emergency vehicle")
                return None
            
            # Get vehicle properties
            props = self.EMER_VEHICLE_TYPES[vehicle_type]
            
            # Generate unique ID using converted timestamp
            ts_int = self._timestamp_to_int(timestamp)
            vehicle_id = f"inj_emergency_{vehicle_type}_{ts_int}"
            
            # Create route (from entry point to a destination)
            route = self._get_emergency_route(entry_point)
            
            if not route:
                logger.warning(f"Could not determine route from {entry_point}")
                return None
            
            # Check if SUMO is connected
            try:
                traci.simulation.getTime()
            except:
                logger.error("SUMO not connected!")
                return None
            
            # Add vehicle to SUMO
            traci.vehicle.add(
                vehID=vehicle_id,
                routeID=route,
                typeID=props['vType'],
                depart=traci.simulation.getTime(),
                departLane='best',
                departSpeed='max'
            )
            
            logger.info(f"Injected emergency vehicle: {vehicle_id} at {entry_point}")
            return vehicle_id
            
        except Exception as e:
            logger.error(f"Error creating emergency vehicle: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def create_normal_vehicles(self, record: Dict[str, Any]) -> List[str]:
        """
        Create multiple normal vehicles from MongoDB record.
        Returns list of created vehicle IDs.
        """
        created_vehicles = []
        
        try:
            # Try to register types
            self._register_EMER_VEHICLE_TYPES()
            
            data = record.get('data', {})
            entry_point = self._normalize_entry_edge(data.get('entryPoint', ''))
            timestamp = record.get('timestamp', '')
            
            if not entry_point:
                logger.warning("No entry point specified for normal vehicles")
                return []
            
            ts_int = self._timestamp_to_int(timestamp)
            
            # Check if SUMO is connected
            try:
                current_time = traci.simulation.getTime()
            except:
                logger.error("SUMO not connected!")
                return []

            # New schema: data.vehicles = [{"type": "bike", "count": 5}, ...]
            vehicle_groups = data.get('vehicles', [])

            # Backward-compatible fallback for old schema with single count.
            if not vehicle_groups and 'count' in data:
                vehicle_groups = [{'type': 'car', 'count': data.get('count', 1)}]

            if not vehicle_groups:
                logger.warning("No vehicle groups provided for normal_vehicle record")
                return []
            
            # Create multiple vehicles with slight delays
            destination_candidates = self._get_destination_candidates(entry_point)
            destination_pool = list(destination_candidates)
            random.shuffle(destination_pool)

            local_index = 0
            max_total = 100

            for group in vehicle_groups:
                requested_type = str(group.get('type', '')).strip()
                normalized_type = self._normalize_normal_vehicle_type(requested_type)
                raw_count = group.get('count', 0)

                try:
                    group_count = int(raw_count)
                except (TypeError, ValueError):
                    logger.warning(f"Invalid count '{raw_count}' for normal type '{requested_type}', skipping")
                    continue

                if not normalized_type:
                    logger.warning(f"Unsupported normal vehicle type: '{requested_type}', skipping")
                    continue

                if group_count <= 0:
                    continue

                runtime_type_id = self.NORM_VEHICLE_TYPES[normalized_type]['vType']

                for _ in range(group_count):
                    if local_index >= max_total:
                        logger.warning("Reached max injected normal vehicles (100) for one record")
                        break

                    vehicle_id = f"inj_normal_{normalized_type}_{ts_int}_{local_index}"
                    local_index += 1

                    if not destination_pool:
                        destination_pool = list(destination_candidates)
                        random.shuffle(destination_pool)

                    preferred_destination = destination_pool.pop()

                    # Determine route based on entry point with randomization per vehicle.
                    route = self._create_runtime_route_random(
                        entry_point,
                        destination_candidates,
                        preferred_first=preferred_destination,
                    )
                
                    if not route:
                        continue
                
                    # Add with slight delay between vehicles
                    depart_time = current_time + (local_index * 0.2)
                
                    traci.vehicle.add(
                        vehID=vehicle_id,
                        routeID=route,
                        typeID=runtime_type_id,
                        depart=depart_time,
                        departLane='best',
                        departSpeed='max'
                    )
                    created_vehicles.append(vehicle_id)

                if local_index >= max_total:
                    break
            
            logger.info(f"Injected {len(created_vehicles)} normal vehicles at {entry_point}")
            return created_vehicles
            
        except Exception as e:
            logger.error(f"Error creating normal vehicles: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def create_pedestrians(self, record: Dict[str, Any]) -> List[str]:
        """
        Create pedestrians at J1 crossing from MongoDB record.
        Returns list of created pedestrian IDs.
        """
        created_peds = []
        
        try:
            # Try to register types
            self._register_EMER_VEHICLE_TYPES()
            
            data = record.get('data', {})
            pedestrians = data.get('pedestrians', [])
            timestamp = record.get('timestamp', '')
            logger.debug(f"Creating pedestrians with data: {pedestrians}")
            
            ts_int = self._timestamp_to_int(timestamp)
            
            # Check if SUMO is connected
            try:
                current_time = traci.simulation.getTime()
            except:
                logger.error("SUMO not connected!")
                return []
            
            for ped_info in pedestrians:
                ped_type = ped_info.get('type', '').lower()
                position = ped_info.get('position', '').lower()
                count = ped_info.get('count', 1)
                
                # Map to our pedestrian types
                type_map = {
                    'elderly': 'elderly',
                    'adult': 'adult',
                    'student': 'student',
                    'mobility_aid': 'mobility_aid'
                }
                
                mapped_type = type_map.get(ped_type, 'adult')
                props = self.PEDESTRIAN_TYPES[mapped_type]
                type_id = props['vType']
                logger.debug(f"Creating pedestrians of type '{mapped_type}' at position '{position}' with count {count}")
                # Determine start and end edges based on position
                north_edges = ['-E0.80', '-E0']
                south_edges = ['E00', 'E0']

                if 'south' in position:
                    # south_side means pedestrian starts south and crosses north.
                    from_edge = random.choice(south_edges)
                    to_edge = random.choice(north_edges)
                else:
                    # north_side means pedestrian starts north and crosses south.
                    from_edge = random.choice(north_edges)
                    to_edge = random.choice(south_edges)
                
                # Create pedestrians
                for i in range(min(count, 5)):  # Limit to 5 at once
                    ped_id = f"ped_{mapped_type}_{ts_int}_{i}"
                    
                    # Add person to SUMO
                    traci.person.add(
                        personID=ped_id,
                        edgeID=from_edge,
                        pos=random.uniform(0, 10),  # Random position along edge
                        depart=current_time + random.uniform(0, 2),
                        typeID=type_id
                    )
                    
                    # Set walking route (cross the junction)
                    traci.person.appendWalkingStage(
                        personID=ped_id,
                        edges=[to_edge],
                        arrivalPos=random.uniform(0, 10)
                    )
                    
                    created_peds.append(ped_id)
            
            logger.info(f"Injected {len(created_peds)} pedestrians at J1")
            return created_peds
            
        except Exception as e:
            logger.error(f"Error creating pedestrians: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _get_emergency_route(self, entry_point: str) -> Optional[str]:
        """Determine and create a runtime route for emergency vehicle."""
        destination_candidates = self._get_destination_candidates(entry_point)
        return self._create_runtime_route_random(entry_point, destination_candidates)
    
    def _get_normal_route(self, entry_point: str) -> Optional[str]:
        """Determine and create a runtime route for normal vehicle."""
        destination_candidates = self._get_destination_candidates(entry_point)
        return self._create_runtime_route_random(entry_point, destination_candidates)