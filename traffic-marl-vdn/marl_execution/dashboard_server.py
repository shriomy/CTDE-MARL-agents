"""
Simple WebSocket server for MARL dashboard.
"""
import asyncio
import websockets
import json
import time
from typing import Set
import threading

class SimpleDashboardServer:
    """Simple WebSocket server for dashboard"""
    
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.connections: Set[websockets.WebSocketServerProtocol] = set()
        self.server = None
        
    async def handler(self, websocket, path):
        """Handle WebSocket connections"""
        self.connections.add(websocket)
        print(f"[Dashboard] New connection from {websocket.remote_address}")
        
        try:
            # Send welcome message
            await websocket.send(json.dumps({
                'type': 'welcome',
                'message': 'Connected to MARL Dashboard',
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
            print(f"[Dashboard] Connection closed from {websocket.remote_address}")
    
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
    
    def send_traffic_update(self, step_data):
        """Send traffic update to dashboard"""
        message = {
            'type': 'traffic_update',
            'timestamp': time.time(),
            'data': step_data
        }
        
        # Run broadcast in event loop
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)
    
    def send_system_status(self, status, message=""):
        """Send system status to dashboard"""
        status_msg = {
            'type': 'system_status',
            'timestamp': time.time(),
            'status': status,
            'message': message
        }
        
        asyncio.run_coroutine_threadsafe(self.broadcast(status_msg), self.loop)
    
    def start(self):
        """Start the WebSocket server in background thread"""
        async def server_main():
            self.server = await websockets.serve(self.handler, self.host, self.port)
            print(f"[Dashboard] WebSocket server started on ws://{self.host}:{self.port}")
            await self.server.wait_closed()
        
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Start server in background thread
        self.thread = threading.Thread(target=self.loop.run_until_complete, args=(server_main(),))
        self.thread.daemon = True
        self.thread.start()
        
        # Give server time to start
        time.sleep(1)