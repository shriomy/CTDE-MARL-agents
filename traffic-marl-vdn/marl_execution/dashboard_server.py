"""WebSocket server for dashboard telemetry and control commands."""

import asyncio
import json
import queue
import threading
import time
from typing import Any, Dict, List, Set

import websockets

class SimpleDashboardServer:
    """WebSocket server that broadcasts telemetry and receives control commands."""

    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.connections: Set[websockets.WebSocketServerProtocol] = set()
        self.server = None
        self.loop = None
        self.thread = None
        self.command_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

    @staticmethod
    def _normalize_command(data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize inbound command payloads."""
        cmd_type = str(data.get("type", "")).strip()
        if not cmd_type:
            return {}

        out: Dict[str, Any] = {
            "type": cmd_type,
            "timestamp": time.time(),
        }

        if "mode" in data:
            out["mode"] = str(data.get("mode", "")).strip().lower()
        if "junction_id" in data:
            out["junction_id"] = str(data.get("junction_id", "")).strip()
        if "action" in data:
            try:
                out["action"] = int(data.get("action"))
            except Exception:
                pass
        if "green_steps" in data:
            try:
                out["green_steps"] = int(data.get("green_steps"))
            except Exception:
                pass
        if "payload" in data and isinstance(data.get("payload"), dict):
            out["payload"] = dict(data.get("payload"))

        return out

    async def handler(self, websocket, path=None):
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
                    msg_type = data.get('type')
                    if msg_type == 'ping':
                        await websocket.send(json.dumps({
                            'type': 'pong',
                            'timestamp': time.time()
                        }))
                        continue

                    command = self._normalize_command(data)
                    if command:
                        self.command_queue.put(command)
                        await websocket.send(json.dumps({
                            'type': 'ack',
                            'accepted_type': command['type'],
                            'timestamp': time.time(),
                        }))
                except:
                    pass

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.connections.discard(websocket)
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
            self.connections.discard(connection)

    def send_traffic_update(self, step_data):
        """Send traffic update to dashboard"""
        if self.loop is None:
            return
        message = {
            'type': 'traffic_update',
            'timestamp': time.time(),
            'data': step_data
        }

        # Run broadcast in event loop
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)

    def send_system_status(self, status, message=""):
        """Send system status to dashboard"""
        if self.loop is None:
            return
        status_msg = {
            'type': 'system_status',
            'timestamp': time.time(),
            'status': status,
            'message': message
        }

        asyncio.run_coroutine_threadsafe(self.broadcast(status_msg), self.loop)

    def send_mode_update(self, runtime_state: Dict[str, Any]) -> None:
        """Broadcast current mode state for all junctions."""
        if self.loop is None:
            return
        msg = {
            "type": "mode_update",
            "timestamp": time.time(),
            "data": runtime_state,
        }
        asyncio.run_coroutine_threadsafe(self.broadcast(msg), self.loop)

    def get_pending_commands(self, max_items: int = 100) -> List[Dict[str, Any]]:
        """Drain received control commands from websocket clients."""
        out: List[Dict[str, Any]] = []
        for _ in range(max(0, int(max_items))):
            try:
                out.append(self.command_queue.get_nowait())
            except queue.Empty:
                break
        return out

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

    def stop(self) -> None:
        """Stop websocket server loop."""
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass