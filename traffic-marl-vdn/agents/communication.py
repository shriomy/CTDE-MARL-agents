import zmq
import json
import numpy as np
from typing import Dict, List, Any
import threading
import time

class AgentCommunication:
    """Handles communication between agents using ZeroMQ"""
    
    def __init__(self, agent_id: str, neighbor_ids: List[str], config: dict):
        self.agent_id = agent_id
        self.neighbor_ids = neighbor_ids
        self.config = config
        
        # Communication context
        self.context = zmq.Context()
        
        # Publisher for this agent
        self.publisher = self.context.socket(zmq.PUB)
        port = 5555 + hash(agent_id) % 100
        self.publisher.bind(f"tcp://*:{port}")
        
        # Subscribers for neighbors
        self.subscribers = {}
        for neighbor_id in neighbor_ids:
            sub = self.context.socket(zmq.SUB)
            neighbor_port = 5555 + hash(neighbor_id) % 100
            sub.connect(f"tcp://localhost:{neighbor_port}")
            sub.setsockopt_string(zmq.SUBSCRIBE, "")
            self.subscribers[neighbor_id] = sub
        
        # Message buffer
        self.received_messages = {}
        self.lock = threading.Lock()
        
        # Start receiver thread
        self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receiver_thread.start()
        
        print(f"Agent {agent_id} communication initialized on port {port}")
    
    def send_state(self, state_info: Dict[str, Any]):
        """Send current state information to neighbors"""
        message = {
            "sender": self.agent_id,
            "timestamp": time.time(),
            "data": state_info,
            "type": "state_update"
        }
        
        self.publisher.send_json(message)
    
    def send_prediction(self, prediction: Dict[str, Any]):
        """Send prediction (e.g., outflow) to neighbors"""
        message = {
            "sender": self.agent_id,
            "timestamp": time.time(),
            "data": prediction,
            "type": "prediction"
        }
        
        self.publisher.send_json(message)
    
    def send_emergency(self, emergency_info: Dict[str, Any]):
        """Send emergency vehicle alert"""
        message = {
            "sender": self.agent_id,
            "timestamp": time.time(),
            "data": emergency_info,
            "type": "emergency",
            "priority": "high"
        }
        
        self.publisher.send_json(message)
    
    def _receive_loop(self):
        """Continuously receive messages from neighbors"""
        poller = zmq.Poller()
        for sub in self.subscribers.values():
            poller.register(sub, zmq.POLLIN)
        
        while True:
            try:
                socks = dict(poller.poll(100))  # 100ms timeout
                
                for sub in socks:
                    message = sub.recv_json(zmq.NOBLOCK)
                    
                    with self.lock:
                        sender = message["sender"]
                        self.received_messages[sender] = {
                            "data": message["data"],
                            "timestamp": message["timestamp"],
                            "type": message.get("type", "unknown")
                        }
                        
            except zmq.Again:
                pass
            except Exception as e:
                print(f"Communication error: {e}")
    
    def get_neighbor_messages(self) -> Dict[str, Any]:
        """Get all received messages from neighbors"""
        with self.lock:
            messages = self.received_messages.copy()
            self.received_messages.clear()
        
        return messages
    
    def close(self):
        """Cleanup communication sockets"""
        self.publisher.close()
        for sub in self.subscribers.values():
            sub.close()
        self.context.term()