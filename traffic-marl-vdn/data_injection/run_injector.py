#!/usr/bin/env python3
"""
Script to run the SUMO data injector.
Can be run alongside MARL training/execution.
"""
import os
import sys
import argparse
import logging
import time
import subprocess
import signal
import threading

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_injection.sumo_injector import SUMODataInjector
from data_injection.mongo_listener import MongoDBListener

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), '..', 'logs', 'injection', 'injector.log'))
    ]
)

logger = logging.getLogger(__name__)

class InjectorRunner:
    """Manages the injector and optionally SUMO"""
    
    def __init__(self, args):
        self.args = args
        self.injector = None
        self.sumo_process = None
        self.running = False
        self.cleaned_up = False
    
    def start_sumo(self):
        """Start SUMO with GUI if requested"""
        if not self.args.sumo_config:
            return
        
        sumo_config = os.path.abspath(self.args.sumo_config)
        if not os.path.exists(sumo_config):
            logger.error(f"SUMO config not found: {sumo_config}")
            return
        
        logger.info(f"Starting SUMO with config: {sumo_config}")
        
        # Choose sumo or sumo-gui
        sumo_binary = "sumo-gui" if self.args.gui else "sumo"
        
        # Important: Add remote port for TraCI connection
        sumo_cmd = [
            sumo_binary, 
            "-c", sumo_config, 
            "--start",  # Auto-start simulation
            "--remote-port", str(self.args.traci_port),  # Enable TraCI on this port
            "--scale", str(self.args.demand_scale),      # Scale route-file demand (0 = injections only)
            "--step-length", str(self.args.step_length),  # Simulation step length in seconds
        ]
        
        try:
            self.sumo_process = subprocess.Popen(
                sumo_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"SUMO started with PID: {self.sumo_process.pid} (auto-start enabled)")
            logger.info(f"TraCI port: {self.args.traci_port}")
            logger.info(f"SUMO demand scale: {self.args.demand_scale}")
            logger.info(f"SUMO step-length: {self.args.step_length}ms")
            
            # Give SUMO time to start
            logger.info("Waiting for SUMO to initialize...")
            time.sleep(5)
            logger.info("SUMO should now be visible and running")
            
        except Exception as e:
            logger.error(f"Failed to start SUMO: {e}")
    
    def stop_sumo(self):
        """Stop SUMO process"""
        if self.sumo_process:
            logger.info("Stopping SUMO...")
            self.sumo_process.terminate()
            try:
                self.sumo_process.wait(timeout=5)
                logger.info("SUMO stopped")
            except subprocess.TimeoutExpired:
                logger.warning("SUMO did not terminate, forcing...")
                self.sumo_process.kill()
            self.sumo_process = None
    
    def signal_handler(self, sig, frame):
        """Handle Ctrl+C"""
        logger.info("\n" + "="*60)
        logger.info("RECEIVED INTERRUPT SIGNAL")
        logger.info("="*60)
        self.running = False
        self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        if self.cleaned_up:
            return
        self.cleaned_up = True

        if self.injector:
            self.injector.stop()
            self.injector.cleanup()
        self.stop_sumo()
    
    def check_mongodb_connection(self):
        """Test MongoDB connection"""
        try:
            logger.info("Testing MongoDB connection...")
            listener = MongoDBListener(
                connection_string=self.args.mongo_uri,
                poll_interval=1
            )
            listener.close()
            logger.info("MongoDB connection successful")
            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False
    
    def run(self):
        """Main run loop"""
        print("\n" + "="*60)
        print("SUMO DATA INJECTOR - REAL-TIME INJECTION")
        print("="*60)
        
        # Check MongoDB first
        if not self.check_mongodb_connection():
            logger.error("Cannot proceed without MongoDB connection")
            return 1
        
        # Start SUMO if requested
        if self.args.sumo_config:
            self.start_sumo()
            if not self.sumo_process:
                logger.error("Failed to start SUMO")
                return 1
        
        # Setup signal handler
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Create injector
        self.injector = SUMODataInjector(
            mongo_uri=self.args.mongo_uri,
            poll_interval=self.args.interval,
            sumo_port=self.args.traci_port
        )
        
        self.running = True
        
        print("\n" + "="*60)
        print("SUMO DATA INJECTOR RUNNING")
        print("="*60)
        print(f"MongoDB: {self.args.mongo_uri}")
        print(f"Poll interval: {self.args.interval}ms")
        print(f"SUMO config: {self.args.sumo_config or 'Not starting SUMO'}")
        print(f"TraCI port: {self.args.traci_port}")
        print("\nWaiting for injection records...")
        print("Press Ctrl+C to stop")
        print("="*60 + "\n")
        
        try:
            # Run injector
            if self.args.duration:
                self.injector.run_for_duration(self.args.duration)
            else:
                self.injector.run()
                
        except Exception as e:
            logger.error(f"Injector error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()
        
        return 0

def main():
    parser = argparse.ArgumentParser(description='SUMO Data Injector from MongoDB')
    
    parser.add_argument('--mongo-uri', 
                       default='mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0',
                       help='MongoDB connection URI')
    
    parser.add_argument('--interval', type=float, default=1.0,
                       help='Polling interval in seconds')
    
    parser.add_argument('--duration', type=int, default=None,
                       help='Run for specified seconds (default: indefinite)')
    
    parser.add_argument('--sumo-config', 
                       help='Path to SUMO config file (starts SUMO automatically)')
    
    parser.add_argument('--gui', action='store_true',
                       help='Use SUMO GUI if starting SUMO')
    
    parser.add_argument('--traci-port', type=int, default=8813,
                       help='TraCI port for SUMO connection (default: 8813)')

    parser.add_argument('--demand-scale', type=float, default=0.0,
                       help='SUMO demand scale for route-file flows/personFlows (default: 0.0, injections only)')

    parser.add_argument('--step-length', type=float, default=1.0,
                       help='SUMO simulation step length in seconds (default: 1.0)')
    
    args = parser.parse_args()
    
    # Create runner and execute
    runner = InjectorRunner(args)
    sys.exit(runner.run())

if __name__ == "__main__":
    main()