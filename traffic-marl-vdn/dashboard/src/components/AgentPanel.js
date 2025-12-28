import React from 'react';
import './AgentPanel.css';

const AgentPanel = ({ agentId, agentData }) => {
  if (!agentData) return null;
  
  const { queues = {}, waiting_times = {}, current_action = {}, current_green = {} } = agentData;
  
  const actionColors = {
    'WEST': '#FF6B6B',
    'NORTH': '#4ECDC4',
    'EAST': '#FFD166',
    'SOUTH': '#06D6A0',
    'EXTEND': '#118AB2'
  };
  
  const getQueueColor = (queue) => {
    if (queue > 15) return '#dc3545';
    if (queue > 10) return '#ffc107';
    if (queue > 5) return '#28a745';
    return '#6c757d';
  };
  
  return (
    <div className="card agent-panel">
      <div className="card-header">
        <h6 className="mb-0">
          <span className="badge bg-dark me-2">Agent</span>
          {agentId}
        </h6>
      </div>
      <div className="card-body">
        <div className="row mb-3">
          <div className="col-12">
            <div className="d-flex justify-content-between align-items-center mb-2">
              <span className="text-muted">Current Action:</span>
              <span 
                className="badge" 
                style={{ backgroundColor: actionColors[current_action.name] || '#6c757d' }}
              >
                {current_action.name || 'None'}
              </span>
            </div>
            <div className="d-flex justify-content-between align-items-center">
              <span className="text-muted">Green Light:</span>
              <span className="badge bg-success">
                {current_green.direction || 'None'}
              </span>
            </div>
          </div>
        </div>
        
        <div className="row">
          <div className="col-12">
            <h6 className="text-muted mb-2">Queue Lengths</h6>
            {['west', 'north', 'east', 'south'].map((direction) => (
              <div key={direction} className="mb-2">
                <div className="d-flex justify-content-between mb-1">
                  <span className="text-capitalize">{direction}</span>
                  <span>{queues[direction]?.toFixed(1) || '0.0'}</span>
                </div>
                <div className="progress" style={{ height: '10px' }}>
                  <div 
                    className="progress-bar" 
                    role="progressbar"
                    style={{
                      width: `${Math.min((queues[direction] || 0) / 20 * 100, 100)}%`,
                      backgroundColor: getQueueColor(queues[direction] || 0)
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
        
        <div className="row mt-3">
          <div className="col-12">
            <h6 className="text-muted mb-2">Waiting Times (s)</h6>
            <div className="row">
              {['west', 'north', 'east', 'south'].map((direction) => (
                <div key={direction} className="col-3 text-center">
                  <div className="card bg-light">
                    <div className="card-body p-2">
                      <small className="text-muted d-block">{direction.charAt(0).toUpperCase()}</small>
                      <strong>{(waiting_times[direction] || 0).toFixed(0)}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        <div className="row mt-3">
          <div className="col-12">
            <div className="card bg-light">
              <div className="card-body p-2 text-center">
                <small className="text-muted">Total Vehicles in Queue</small>
                <h4 className="mb-0">{queues.total?.toFixed(0) || '0'}</h4>
                <small>Avg Wait: {(waiting_times.average || 0).toFixed(1)}s</small>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AgentPanel;