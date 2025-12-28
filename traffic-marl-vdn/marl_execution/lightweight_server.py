"""
Lightweight WebSocket server for real-time dashboard updates.
This will broadcast agent decisions and traffic metrics to a React dashboard.
"""
import asyncio
import websockets
import json
import time
from threading import Thread
from typing import Dict, List, Any

class LightweightDashboardServer:
    """WebSocket server for real-time MARL execution visualization"""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.connections = set()
        self.data_buffer = []
        self.running = False
        
    async def register(self, websocket):
        """Register new WebSocket connection"""
        self.connections.add(websocket)
        print(f"New dashboard connection: {websocket.remote_address}")
        
        # Send initial data if available
        if self.data_buffer:
            await websocket.send(json.dumps({
                "type": "initial_data",
                "data": self.data_buffer[-100:]  # Last 100 data points
            }))
    
    async def unregister(self, websocket):
        """Unregister WebSocket connection"""
        self.connections.remove(websocket)
        print(f"Dashboard disconnected: {websocket.remote_address}")
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected dashboards"""
        if self.connections:
            message_json = json.dumps(message)
            await asyncio.gather(
                *[connection.send(message_json) for connection in self.connections]
            )
    
    def send_traffic_update(self, step_data: Dict[str, Any]):
        """Send traffic update (called from main execution thread)"""
        # This runs in a separate thread, so we need thread-safe broadcast
        asyncio.run_coroutine_threadsafe(
            self.broadcast({
                "type": "traffic_update",
                "timestamp": time.time(),
                "data": step_data
            }),
            self.loop
        )
        
        # Store in buffer (keep last 1000 updates)
        self.data_buffer.append(step_data)
        if len(self.data_buffer) > 1000:
            self.data_buffer.pop(0)
    
    def send_agent_decision(self, agent_id: str, action: int, state: Dict[str, Any]):
        """Send agent decision update"""
        asyncio.run_coroutine_threadsafe(
            self.broadcast({
                "type": "agent_decision",
                "timestamp": time.time(),
                "agent_id": agent_id,
                "action": action,
                "state": state
            }),
            self.loop
        )
    
    def send_system_status(self, status: str, message: str = ""):
        """Send system status update"""
        asyncio.run_coroutine_threadsafe(
            self.broadcast({
                "type": "system_status",
                "timestamp": time.time(),
                "status": status,
                "message": message
            }),
            self.loop
        )
    
    async def handler(self, websocket, path):
        """WebSocket connection handler"""
        await self.register(websocket)
        try:
            async for message in websocket:
                # Handle incoming messages from dashboard
                data = json.loads(message)
                print(f"Received from dashboard: {data}")
                
                # Echo back for now
                await websocket.send(json.dumps({
                    "type": "echo",
                    "timestamp": time.time(),
                    "received": data
                }))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)
    
    def start_server(self):
        """Start WebSocket server in background thread"""
        self.running = True
        
        async def server_main():
            async with websockets.serve(self.handler, self.host, self.port):
                print(f"WebSocket server started on ws://{self.host}:{self.port}")
                print("Dashboard can connect to receive real-time updates")
                await asyncio.Future()  # Run forever
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        self.server_thread = Thread(target=self.loop.run_until_complete, args=(server_main(),))
        self.server_thread.daemon = True
        self.server_thread.start()
    
    def stop_server(self):
        """Stop WebSocket server"""
        self.running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)