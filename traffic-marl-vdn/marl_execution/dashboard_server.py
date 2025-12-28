"""
Enhanced WebSocket server for MARL traffic control dashboard.
This handles real-time bidirectional communication with the React dashboard.
"""
import asyncio
import websockets
import json
import time
import threading
from typing import Dict, List, Any, Set
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MARLDashboardServer:
    """WebSocket server for real-time MARL execution visualization"""
    
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self.connections: Set[websockets.WebSocketServerProtocol] = set()
        self.history_buffer: List[Dict] = []
        self.MAX_HISTORY = 1000
        
        # Agent state cache
        self.agent_states: Dict[str, Dict] = {}
        self.system_state: Dict = {
            'status': 'stopped',
            'message': 'Server started, waiting for connection',
            'step': 0,
            'total_reward': 0,
            'vehicle_count': 0,
            'avg_speed': 0,
            'timestamp': time.time()
        }
        
        # Traffic metrics
        self.traffic_metrics: Dict = {
            'queue_history': [],
            'reward_history': [],
            'action_history': [],
            'throughput': 0
        }
        
        # Start server in background thread
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        
        logger.info(f"MARL Dashboard Server initialized on ws://{host}:{port}")
    
    def _run_server(self):
        """Run WebSocket server in its own thread"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        start_server = websockets.serve(self._handler, self.host, self.port)
        
        try:
            loop.run_until_complete(start_server)
            logger.info(f"WebSocket server started successfully on ws://{self.host}:{self.port}")
            loop.run_forever()
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
        finally:
            loop.close()
    
    async def _handler(self, websocket, path):
        """Handle WebSocket connections"""
        await self._register(websocket)
        try:
            async for message in websocket:
                await self._handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            await self._unregister(websocket)
        except Exception as e:
            logger.error(f"Handler error: {e}")
            await self._unregister(websocket)
    
    async def _register(self, websocket):
        """Register new WebSocket connection"""
        self.connections.add(websocket)
        logger.info(f"New dashboard connection: {websocket.remote_address}")
        
        # Send initial state
        await self._send_initial_state(websocket)
    
    async def _unregister(self, websocket):
        """Unregister WebSocket connection"""
        if websocket in self.connections:
            self.connections.remove(websocket)
            logger.info(f"Dashboard disconnected: {websocket.remote_address}")
    
    async def _send_initial_state(self, websocket):
        """Send initial state to new connection"""
        initial_data = {
            'type': 'initial_state',
            'timestamp': time.time(),
            'system': self.system_state,
            'agents': self.agent_states,
            'history': self.history_buffer[-100:],  # Last 100 updates
            'metrics': self.traffic_metrics
        }
        
        try:
            await websocket.send(json.dumps(initial_data))
            logger.info(f"Sent initial state to {websocket.remote_address}")
        except Exception as e:
            logger.error(f"Failed to send initial state: {e}")
    
    async def _handle_message(self, websocket, message):
        """Handle incoming messages from dashboard"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', 'unknown')
            
            if msg_type == 'ping':
                await self._send_pong(websocket)
            elif msg_type == 'command':
                await self._handle_command(websocket, data)
            elif msg_type == 'request_history':
                await self._send_history(websocket, data.get('limit', 100))
            elif msg_type == 'update_settings':
                await self._update_settings(data.get('settings', {}))
            else:
                logger.warning(f"Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {message}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _send_pong(self, websocket):
        """Send pong response"""
        pong = {
            'type': 'pong',
            'timestamp': time.time()
        }
        await websocket.send(json.dumps(pong))
    
    async def _handle_command(self, websocket, data):
        """Handle commands from dashboard"""
        command = data.get('command', '')
        
        response = {
            'type': 'command_response',
            'timestamp': time.time(),
            'command': command,
            'status': 'success'
        }
        
        if command == 'get_agent_details':
            agent_id = data.get('agent_id', '')
            if agent_id in self.agent_states:
                response['data'] = self.agent_states[agent_id]
            else:
                response['status'] = 'error'
                response['message'] = f'Agent {agent_id} not found'
        
        elif command == 'get_system_info':
            response['data'] = {
                'connections': len(self.connections),
                'history_size': len(self.history_buffer),
                'uptime': time.time() - self.system_state.get('start_time', time.time()),
                'agent_count': len(self.agent_states)
            }
        
        elif command == 'clear_history':
            self.history_buffer.clear()
            response['message'] = 'History cleared'
        
        await websocket.send(json.dumps(response))
    
    async def _send_history(self, websocket, limit):
        """Send history data"""
        history = self.history_buffer[-limit:] if limit < len(self.history_buffer) else self.history_buffer
        response = {
            'type': 'history_data',
            'timestamp': time.time(),
            'limit': limit,
            'data': history
        }
        await websocket.send(json.dumps(response))
    
    async def _update_settings(self, settings):
        """Update server settings"""
        # For now, just log settings updates
        logger.info(f"Settings updated: {settings}")
    
    async def _broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        if not self.connections:
            return
        
        message_json = json.dumps(message)
        dead_connections = []
        
        for connection in self.connections:
            try:
                await connection.send(message_json)
            except Exception as e:
                logger.error(f"Failed to send to {connection.remote_address}: {e}")
                dead_connections.append(connection)
        
        # Clean up dead connections
        for connection in dead_connections:
            await self._unregister(connection)
    
    # Public methods for the executor to call
    def send_traffic_update(self, step_data: Dict[str, Any]):
        """Send traffic update from executor"""
        update_message = {
            'type': 'traffic_update',
            'timestamp': time.time(),
            'data': step_data
        }
        
        # Store in history
        self.history_buffer.append(update_message)
        if len(self.history_buffer) > self.MAX_HISTORY:
            self.history_buffer.pop(0)
        
        # Update system state
        self.system_state.update({
            'step': step_data.get('step', 0),
            'total_reward': step_data.get('total_reward', 0),
            'vehicle_count': step_data.get('vehicle_count', 0),
            'avg_speed': step_data.get('avg_speed', 0),
            'timestamp': time.time()
        })
        
        # Broadcast asynchronously
        asyncio.run_coroutine_threadsafe(
            self._broadcast(update_message),
            asyncio.get_event_loop()
        )
    
    def send_agent_update(self, agent_id: str, agent_data: Dict[str, Any]):
        """Send individual agent update"""
        self.agent_states[agent_id] = agent_data
        
        update_message = {
            'type': 'agent_update',
            'timestamp': time.time(),
            'agent_id': agent_id,
            'data': agent_data
        }
        
        asyncio.run_coroutine_threadsafe(
            self._broadcast(update_message),
            asyncio.get_event_loop()
        )
    
    def send_system_status(self, status: str, message: str = ""):
        """Send system status update"""
        self.system_state['status'] = status
        self.system_state['message'] = message
        
        status_message = {
            'type': 'system_status',
            'timestamp': time.time(),
            'status': status,
            'message': message
        }
        
        asyncio.run_coroutine_threadsafe(
            self._broadcast(status_message),
            asyncio.get_event_loop()
        )
    
    def update_metrics(self, metrics: Dict[str, Any]):
        """Update traffic metrics"""
        self.traffic_metrics.update(metrics)
        
        metrics_message = {
            'type': 'metrics_update',
            'timestamp': time.time(),
            'metrics': self.traffic_metrics
        }
        
        asyncio.run_coroutine_threadsafe(
            self._broadcast(metrics_message),
            asyncio.get_event_loop()
        )
    
    def get_server_info(self) -> Dict[str, Any]:
        """Get server information"""
        return {
            'host': self.host,
            'port': self.port,
            'connections': len(self.connections),
            'status': 'running',
            'history_size': len(self.history_buffer),
            'agent_count': len(self.agent_states)
        }