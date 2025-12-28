import React, { useState, useEffect, useRef } from 'react';
import 'bootstrap/dist/css/bootstrap.min.css';
import AgentPanel from './components/AgentPanel';
import TrafficChart from './components/TrafficChart';
import SystemStatus from './components/SystemStatus';
import RealTimeTable from './components/RealTimeTable';
import './App.css';

function App() {
  const [connectionStatus, setConnectionStatus] = useState('disconnected');
  const [systemState, setSystemState] = useState({
    step: 0,
    totalReward: 0,
    vehicleCount: 0,
    avgSpeed: 0,
    status: 'Initializing...'
  });
  const [agents, setAgents] = useState({});
  const [trafficData, setTrafficData] = useState([]);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  const connectWebSocket = () => {
    const ws = new WebSocket('ws://localhost:8765');
    
    ws.onopen = () => {
      console.log('Connected to MARL WebSocket server');
      setConnectionStatus('connected');
      setSystemState(prev => ({ ...prev, status: 'Connected, waiting for data...' }));
      
      // Clear any pending reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };
    
    ws.onclose = () => {
      console.log('Disconnected from WebSocket server');
      setConnectionStatus('disconnected');
      setSystemState(prev => ({ ...prev, status: 'Disconnected, attempting to reconnect...' }));
      
      // Attempt to reconnect after 3 seconds
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setSystemState(prev => ({ ...prev, status: 'Connection error' }));
    };
    
    wsRef.current = ws;
  };

  const handleWebSocketMessage = (data) => {
    switch (data.type) {
      case 'traffic_update':
        handleTrafficUpdate(data.data);
        break;
      case 'agent_update':
        handleAgentUpdate(data.agent_id, data.data);
        break;
      case 'system_status':
        handleSystemStatus(data.status, data.message);
        break;
      case 'initial_state':
        handleInitialState(data);
        break;
      case 'metrics_update':
        handleMetricsUpdate(data.metrics);
        break;
      case 'pong':
        // Handle pong response
        break;
      default:
        console.log('Unknown message type:', data.type);
    }
  };

  const handleTrafficUpdate = (stepData) => {
    // Update system state
    setSystemState(prev => ({
      ...prev,
      step: stepData.step,
      totalReward: stepData.total_reward,
      vehicleCount: stepData.vehicle_count,
      avgSpeed: stepData.avg_speed
    }));
    
    // Add to traffic data history
    setTrafficData(prev => {
      const newData = [...prev, {
        ...stepData,
        timestamp: new Date().toLocaleTimeString()
      }];
      // Keep only last 100 data points
      return newData.slice(-100);
    });
  };

  const handleAgentUpdate = (agentId, agentData) => {
    setAgents(prev => ({
      ...prev,
      [agentId]: agentData
    }));
  };

  const handleSystemStatus = (status, message) => {
    setSystemState(prev => ({
      ...prev,
      status: `${status}: ${message}`
    }));
  };

  const handleInitialState = (data) => {
    console.log('Received initial state:', data);
    if (data.agents) {
      setAgents(data.agents);
    }
    if (data.system) {
      setSystemState(data.system);
    }
  };

  const handleMetricsUpdate = (metrics) => {
    // Update charts or other metrics displays
    console.log('Metrics update:', metrics);
  };

  const sendCommand = (command, data = {}) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const message = {
        type: 'command',
        command,
        ...data,
        timestamp: Date.now()
      };
      wsRef.current.send(JSON.stringify(message));
    }
  };

  useEffect(() => {
    connectWebSocket();
    
    // Cleanup on unmount
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, []);

  return (
    <div className="container-fluid mt-3">
      <div className="row mb-4">
        <div className="col">
          <h1 className="display-4">🚦 MARL Traffic Control Dashboard</h1>
          <p className="lead">Real-time monitoring of decentralized multi-agent traffic signal control</p>
        </div>
      </div>

      <SystemStatus 
        connectionStatus={connectionStatus}
        systemState={systemState}
        agentsCount={Object.keys(agents).length}
      />

      <div className="row mt-4">
        <div className="col-lg-8">
          <div className="card">
            <div className="card-header bg-primary text-white">
              <h5 className="mb-0">Agent Control Panels</h5>
            </div>
            <div className="card-body">
              <div className="row">
                {Object.entries(agents).map(([agentId, agentData]) => (
                  <div className="col-md-6 mb-3" key={agentId}>
                    <AgentPanel agentId={agentId} agentData={agentData} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="col-lg-4">
          <div className="card">
            <div className="card-header bg-success text-white">
              <h5 className="mb-0">Traffic Overview</h5>
            </div>
            <div className="card-body">
              <TrafficChart trafficData={trafficData} />
            </div>
          </div>
        </div>
      </div>

      <div className="row mt-4">
        <div className="col-12">
          <div className="card">
            <div className="card-header bg-info text-white">
              <h5 className="mb-0">Real-time Traffic Updates</h5>
            </div>
            <div className="card-body">
              <RealTimeTable trafficData={trafficData} />
            </div>
          </div>
        </div>
      </div>

      <div className="row mt-4">
        <div className="col-12">
          <div className="card">
            <div className="card-header bg-secondary text-white">
              <h5 className="mb-0">System Controls</h5>
            </div>
            <div className="card-body">
              <div className="btn-group" role="group">
                <button 
                  className="btn btn-outline-primary"
                  onClick={() => sendCommand('get_system_info')}
                >
                  Refresh System Info
                </button>
                <button 
                  className="btn btn-outline-warning"
                  onClick={() => sendCommand('clear_history')}
                >
                  Clear History
                </button>
                <button 
                  className="btn btn-outline-danger"
                  onClick={() => {
                    if (wsRef.current) {
                      wsRef.current.close();
                    }
                  }}
                >
                  Disconnect
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <footer className="mt-5 text-center text-muted">
        <p>MARL Traffic Control System • Real-time Dashboard • {new Date().getFullYear()}</p>
        <p className="small">WebSocket: ws://localhost:8765 • React Dashboard • SUMO Integration</p>
      </footer>
    </div>
  );
}

export default App;