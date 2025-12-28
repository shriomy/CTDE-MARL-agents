"""
Fixed-time traffic control with WebSocket dashboard.
"""
import os
import sys
import time
import json
import threading
from datetime import datetime
import traci

# Add parent directory to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(project_root, ".."))

from fixed_time_controller import FixedTimeController

# Simple WebSocket server for dashboard
import asyncio
import websockets

class SimpleDashboardServer:
    """Simple WebSocket server for fixed-time dashboard"""
    
    def __init__(self, host="localhost", port=8766):  # Different port than MARL
        self.host = host
        self.port = port
        self.connections = set()
        self.server = None
        self.loop = None
        
    async def handler(self, websocket, path):
        """Handle WebSocket connections"""
        self.connections.add(websocket)
        print(f"[Fixed Dashboard] New connection from {websocket.remote_address}")
        
        try:
            # Send welcome message
            await websocket.send(json.dumps({
                'type': 'welcome',
                'message': 'Connected to Fixed-Time Traffic Dashboard',
                'timestamp': time.time()
            }))
            
            # Keep connection alive
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'ping':
                        await websocket.send(json.dumps({
                            'type': 'pong',
                            'timestamp': time.time()
                        }))
                except:
                    pass
                    
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connections.remove(websocket)
            print(f"[Fixed Dashboard] Connection closed from {websocket.remote_address}")
    
    async def broadcast(self, message):
        """Broadcast message to all connected clients"""
        if not self.connections:
            return
        
        message_json = json.dumps(message)
        disconnected = []
        
        for connection in self.connections:
            try:
                await connection.send(message_json)
            except:
                disconnected.append(connection)
        
        for connection in disconnected:
            self.connections.remove(connection)
    
        print("\nChecking vehicle routes...")

        # Give SUMO a few steps to load vehicles
        for _ in range(10):
            traci.simulationStep()
            
        vehicle_count = traci.vehicle.getIDCount()
        print(f"Vehicles after 10 steps: {vehicle_count}")

        if vehicle_count == 0:
            print("\n⚠ WARNING: No vehicles detected in simulation!")
            print("This could mean:")
            print("1. Route file not found or empty")
            print("2. Simulation time not long enough")
            print("3. Vehicle insertion rate is 0")
            
            # Check routes
            try:
                route_count = traci.route.getIDCount()
                print(f"Routes defined: {route_count}")
                
                if route_count == 0:
                    print("❌ ERROR: No routes defined!")
                    print("Please check your .rou.xml file")
                else:
                    print("Routes found, waiting for vehicles to appear...")
            except:
                print("Could not check routes")

    def send_traffic_update(self, step_data):
        """Send traffic update to dashboard"""
        message = {
            'type': 'traffic_update',
            'timestamp': time.time(),
            'data': step_data
        }
        
        # Run broadcast in event loop
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)
    
    def send_system_status(self, status, message=""):
        """Send system status to dashboard"""
        status_msg = {
            'type': 'system_status',
            'timestamp': time.time(),
            'status': status,
            'message': message
        }
        
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.broadcast(status_msg), self.loop)
    
    def start(self):
        """Start the WebSocket server in background thread"""
        async def server_main():
            self.server = await websockets.serve(self.handler, self.host, self.port)
            print(f"[Fixed Dashboard] WebSocket server started on ws://{self.host}:{self.port}")
            await self.server.wait_closed()
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Start server in background thread
        self.thread = threading.Thread(target=self.loop.run_until_complete, args=(server_main(),))
        self.thread.daemon = True
        self.thread.start()
        
        # Give server time to start
        time.sleep(1)

class FixedTimeExecutor:
    """Fixed-time traffic control executor with dashboard"""
    
    def __init__(self):
        # Configuration
        config_path = os.path.join(project_root, "..", "sumo_configs", "1x2.sumocfg")
        
        if not os.path.exists(config_path):
            print(f"✗ ERROR: SUMO config not found at {config_path}")
            sys.exit(1)
        
        # Initialize dashboard server
        print("\nStarting Fixed-Time Dashboard Server...")
        self.dashboard = SimpleDashboardServer(host="localhost", port=8766)
        self.dashboard.start()
        
        # Initialize controller
        print("Starting Fixed-Time Controller...")
        self.controller = FixedTimeController(config_path)
        self.controller.start()
        
        # Metrics
        self.total_reward = 0
        self.total_steps = 0
        
        print("\n" + "="*60)
        print("FIXED-TIME TRAFFIC CONTROL")
        print("="*60)
        print(f"Dashboard: ws://localhost:8766")
        print(f"Open fixed_time_dashboard.html in browser")
        print("="*60)
    
    def run(self, num_steps=1800):
        """Run fixed-time control"""
        print(f"\nRunning fixed-time control for {num_steps} steps...")
        print("Press Ctrl+C to stop\n")
        
        self.dashboard.send_system_status("executing", f"Running for {num_steps} steps")
        
        try:
            for step, state, metrics in self.controller.run_for_steps(num_steps):
                self.total_reward += metrics['reward']
                self.total_steps = step + 1
                
                # Prepare and send dashboard data
                dashboard_data = self.controller.get_dashboard_data(state, metrics)
                self.dashboard.send_traffic_update(dashboard_data)
                
                # Small delay for visualization
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n\nExecution stopped by user")
            self.dashboard.send_system_status("stopped", "Execution stopped by user")
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
            self.dashboard.send_system_status("error", f"Error: {str(e)}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        print("\nCleaning up...")
        
        # Save metrics
        self.save_metrics()
        
        # Close SUMO
        self.controller.close()
        
        # Final dashboard update
        self.dashboard.send_system_status(
            "shutdown", 
            f"Execution complete. Total steps: {self.total_steps}, "
            f"Total reward: {self.total_reward:.2f}"
        )
        
        print("\n✓ Cleanup complete")
    
    def save_metrics(self):
        """Save execution metrics"""
        log_dir = os.path.join(project_root, "..", "logs", "fixed_time")
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get controller metrics
        metrics = {
            'total_steps': self.total_steps,
            'total_reward': float(self.total_reward),
            'avg_reward': float(self.total_reward / self.total_steps if self.total_steps > 0 else 0),
            'queue_history': self.controller.metrics['queue_history'],
            'waiting_history': self.controller.metrics['waiting_history'],
            'vehicle_history': self.controller.metrics['vehicle_history'],
            'speed_history': self.controller.metrics['speed_history'],
            'timestamp': timestamp,
            'controller_type': 'fixed_time',
            'cycle_times': self.controller.cycle
        }
        
        # Save to file
        metrics_file = os.path.join(log_dir, f"fixed_time_{timestamp}.json")
        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        
        print(f"\n✓ Metrics saved to: {metrics_file}")
        
        # Print summary
        print(f"\nExecution Summary:")
        print(f"  Total Steps: {self.total_steps}")
        print(f"  Total Reward: {self.total_reward:.2f}")
        print(f"  Avg Reward per Step: {self.total_reward/self.total_steps:.4f}")
        
        if self.controller.metrics['queue_history']:
            avg_queue = sum(self.controller.metrics['queue_history']) / len(self.controller.metrics['queue_history'])
            avg_wait = sum(self.controller.metrics['waiting_history']) / len(self.controller.metrics['waiting_history'])
            print(f"  Average Queue: {avg_queue:.1f}")
            print(f"  Average Wait: {avg_wait:.1f}s")

def main():
    """Main function"""
    print("="*60)
    print("FIXED-TIME TRAFFIC CONTROL")
    print("="*60)
    print("This will run traffic lights with fixed timing:")
    print("  Cycle: West(30s) → North(30s) → East(30s) → South(30s)")
    print("  Yellow time: 3s")
    print("="*60)
    
    executor = FixedTimeExecutor()
    executor.run(num_steps=1800)  # Run for 1800 steps (30 minutes simulation)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExecution cancelled by user")
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()