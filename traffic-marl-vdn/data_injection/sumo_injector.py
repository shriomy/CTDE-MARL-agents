"""
Main SUMO Injector class that connects MongoDB listener to SUMO.
Runs alongside your MARL training/execution.
"""
import os
import sys
import time
import logging
import traci
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_injection.mongo_listener import MongoDBListener
from data_injection.vehicle_factory import SUMOVehicleFactory

logger = logging.getLogger(__name__)

class SUMODataInjector:
    """
    Real-time data injector from MongoDB to SUMO.
    Runs in parallel with MARL training/execution.
    """
    
    def __init__(self, 
                 mongo_uri: str = "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
                 poll_interval: float = 1.0,
                 sumo_port: int = 8813,  # Default TraCI port
                 log_injections: bool = True):
        
        self.mongo_uri = mongo_uri
        self.poll_interval = poll_interval
        self.sumo_port = sumo_port
        self.log_injections = log_injections
        self.running = False
        self.sumo_connected = False
        self.cleaned_up = False
        
        logger.info("Initializing SUMO Data Injector...")
        
        # Initialize MongoDB listener
        self.listener = MongoDBListener(
            connection_string=mongo_uri,
            poll_interval=poll_interval
        )
        
        # Initialize vehicle factory
        self.factory = SUMOVehicleFactory()
        
        # Track injected entities
        self.injected_vehicles = []
        self.injected_pedestrians = []
        self.last_injection_time = 0
        self._last_poll_wall_time = 0.0
        
        # Setup logging
        if log_injections:
            self._setup_logging()
    
    def _setup_logging(self):
        """Setup injection logging"""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'injection')
        os.makedirs(log_dir, exist_ok=True)
        
        # Add file handler for injection logs
        file_handler = logging.FileHandler(os.path.join(log_dir, 'injections.log'))
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    
    def connect_to_sumo(self):
        """Connect to running SUMO instance via TraCI"""
        try:
            # Try to connect to SUMO on the specified port
            traci.init(self.sumo_port)
            self.sumo_connected = True
            logger.info(f"Connected to SUMO on port {self.sumo_port}")
            
            # Get simulation info
            sim_time = traci.simulation.getTime()
            vehicles = traci.vehicle.getIDList()
            logger.info(f"   Simulation time: {sim_time}ms")
            logger.info(f"   Vehicles in simulation: {len(vehicles)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to SUMO: {e}")
            logger.info("Make sure SUMO is running with --remote-port option")
            return False
    
    def disconnect_from_sumo(self):
        """Disconnect from SUMO"""
        if self.sumo_connected:
            try:
                traci.close()
                logger.info("Disconnected from SUMO")
            except:
                pass
            self.sumo_connected = False
    
    def process_records(self, records: List[Dict[str, Any]]):
        """
        Process a batch of records from MongoDB and inject into SUMO.
        """
        if not records:
            return
        
        # Check SUMO connection
        if not self.sumo_connected:
            logger.warning("Not connected to SUMO, skipping injection")
            return
        
        logger.info(f"Processing {len(records)} records for injection")
        
        for record in records:
            record_type = record.get('type')
            timestamp = record.get('timestamp', 'unknown')
            
            logger.info(f"Record: type={record_type}, timestamp={timestamp}")
            
            try:
                if record_type == 'emergency_vehicle':
                    self._inject_emergency(record)
                    
                elif record_type == 'pedestrian':
                    self._inject_pedestrians(record)
                    
                elif record_type == 'normal_vehicle':
                    self._inject_normal_vehicles(record)
                    
                else:
                    logger.warning(f"Unknown record type: {record_type}")
                    
            except Exception as e:
                logger.error(f"Error processing record {record.get('_id')}: {e}")
                import traceback
                traceback.print_exc()
        
        self.last_injection_time = time.time()
    
    def _inject_emergency(self, record: Dict[str, Any]):
        """Inject emergency vehicle"""
        try:
            logger.info(f"Attempting to inject emergency vehicle: {record.get('data', {})}")
            vehicle_id = self.factory.create_emergency_vehicle(record)
            if vehicle_id:
                self.injected_vehicles.append({
                    'id': vehicle_id,
                    'type': 'emergency',
                    'timestamp': record['timestamp'],
                    'data': record.get('data', {})
                })
                logger.info(f"SUCCESS: Injected emergency vehicle: {vehicle_id}")
            else:
                logger.warning("Failed to create emergency vehicle")
        except Exception as e:
            logger.error(f"Emergency vehicle injection failed: {e}")
    
    def _inject_pedestrians(self, record: Dict[str, Any]):
        """Inject pedestrians"""
        try:
            logger.info(f"Attempting to inject pedestrians: {record.get('data', {})}")
            ped_ids = self.factory.create_pedestrians(record)
            if ped_ids:
                for ped_id in ped_ids:
                    self.injected_pedestrians.append({
                        'id': ped_id,
                        'timestamp': record['timestamp'],
                        'data': record.get('data', {})
                    })
                logger.info(f"SUCCESS: Injected {len(ped_ids)} pedestrians")
            else:
                logger.warning("Failed to create pedestrians")
        except Exception as e:
            logger.error(f"Pedestrian injection failed: {e}")
    
    def _inject_normal_vehicles(self, record: Dict[str, Any]):
        """Inject normal vehicles"""
        try:
            logger.info(f"Attempting to inject normal vehicles: {record.get('data', {})}")
            vehicle_ids = self.factory.create_normal_vehicles(record)
            if vehicle_ids:
                for vid in vehicle_ids:
                    self.injected_vehicles.append({
                        'id': vid,
                        'type': 'normal',
                        'timestamp': record['timestamp'],
                        'data': record.get('data', {})
                    })
                logger.info(f"SUCCESS: Injected {len(vehicle_ids)} normal vehicles")
            else:
                logger.warning("Failed to create normal vehicles")
        except Exception as e:
            logger.error(f"Normal vehicle injection failed: {e}")
    
    def run(self):
        """
        Run the injector continuously.
        """
        logger.info("="*60)
        logger.info("STARTING SUMO DATA INJECTOR")
        logger.info("="*60)
        logger.info(f"MongoDB: {self.mongo_uri}")
        logger.info(f"Poll interval: {self.poll_interval}ms")
        logger.info(f"SUMO port: {self.sumo_port}")
        logger.info("="*60)
        
        # Connect to SUMO
        if not self.connect_to_sumo():
            logger.error("Cannot proceed without SUMO connection")
            return
        
        self.running = True
        poll_count = 0
        self._last_poll_wall_time = time.monotonic()
        
        try:
            # Manual polling loop
            while self.running:
                # With TraCI control, simulation only advances when stepped.
                traci.simulationStep()

                poll_count += 1
                if poll_count % 50 == 0:  # Log periodically without flooding output
                    logger.info(f"Simulation stepping... (step #{poll_count})")
                    # Also log simulation status
                    try:
                        sim_time = traci.simulation.getTime()
                        vehicles = len(traci.vehicle.getIDList())
                        logger.info(f"   SUMO status: time={sim_time:.1f}ms, vehicles={vehicles}")
                    except:
                        logger.warning("   SUMO connection lost!")
                        self.sumo_connected = False
                        break
                
                # Poll MongoDB on wall-clock cadence while keeping SUMO stepping responsive.
                now = time.monotonic()
                if now - self._last_poll_wall_time >= self.poll_interval:
                    records = self.listener.get_new_records()
                    if records:
                        logger.info(f"Found {len(records)} new records to inject!")
                        self.process_records(records)
                    self._last_poll_wall_time = now
            
        except KeyboardInterrupt:
            logger.info("Injector stopped by user")
        except Exception as e:
            logger.error(f"Injector error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def run_for_duration(self, seconds: int):
        """Run for specified duration"""
        logger.info(f"Running injector for {seconds} seconds")
        
        # Connect to SUMO
        if not self.connect_to_sumo():
            logger.error("Cannot proceed without SUMO connection")
            return
        
        start_time = time.time()
        self._last_poll_wall_time = time.monotonic()
        
        try:
            while time.time() - start_time < seconds:
                traci.simulationStep()
                now = time.monotonic()
                if now - self._last_poll_wall_time >= self.poll_interval:
                    records = self.listener.get_new_records()
                    self.process_records(records)
                    self._last_poll_wall_time = now
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()
    
    def stop(self):
        """Stop the injector"""
        self.running = False
    
    def cleanup(self):
        """Cleanup resources"""
        if self.cleaned_up:
            return
        self.cleaned_up = True

        logger.info("="*60)
        logger.info("CLEANING UP INJECTOR")
        logger.info("="*60)
        
        # Disconnect from SUMO
        self.disconnect_from_sumo()
        
        # Print statistics
        logger.info("\nInjection Statistics:")
        logger.info(f"   Total vehicles injected: {len(self.injected_vehicles)}")
        logger.info(f"   - Emergency: {sum(1 for v in self.injected_vehicles if v['type'] == 'emergency')}")
        emergency_types = {}
        for v in self.injected_vehicles:
            if v['type'] == 'emergency':
                veh_type = v['data'].get('vehicle_type', 'unknown')
                emergency_types[veh_type] = emergency_types.get(veh_type, 0) + 1
        for veh_type, count in emergency_types.items():
            logger.info(f"     * {veh_type}: {count}")
        logger.info(f"   - Normal: {sum(1 for v in self.injected_vehicles if v['type'] == 'normal')}")
        logger.info(f"   Total pedestrians injected: {len(self.injected_pedestrians)}")
        
        # Close MongoDB connection
        self.listener.close()
        
        logger.info("Injector cleanup complete")