// MARL Traffic Control Dashboard - Real-time Visualization

// Configuration
const WS_URL = 'ws://localhost:8765';
const ACTION_COLORS = {
    0: '#FF6B6B',  // West - Red
    1: '#4ECDC4',  // North - Teal
    2: '#FFD166',  // East - Yellow
    3: '#06D6A0',  // South - Green
    4: '#118AB2'   // Extend - Blue
};

const ACTION_NAMES = {
    0: 'WEST',
    1: 'NORTH',
    2: 'EAST',
    3: 'SOUTH',
    4: 'EXTEND'
};

const DIRECTION_LABELS = ['West', 'North', 'East', 'South'];

// State
let ws = null;
let isConnected = false;
let agents = {};
let stepHistory = [];
let communicationLog = [];
let charts = {};

// DOM Elements
const connectionStatus = document.getElementById('connectionStatus');
const totalSteps = document.getElementById('totalSteps');
const totalReward = document.getElementById('totalReward');
const vehicleCount = document.getElementById('vehicleCount');
const avgSpeed = document.getElementById('avgSpeed');
const currentActions = document.getElementById('currentActions');
const agentPanels = document.getElementById('agentPanels');
const communicationLogDiv = document.getElementById('communicationLog');

// Initialize WebSocket connection
function connectWebSocket() {
    console.log(`Connecting to WebSocket server at ${WS_URL}...`);
    
    ws = new WebSocket(WS_URL);
    
    ws.onopen = function() {
        console.log('✅ Connected to MARL WebSocket server');
        isConnected = true;
        updateConnectionStatus('Connected', 'status-connected');
        showNotification('Connected to MARL server', 'success');
    };
    
    ws.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    };
    
    ws.onclose = function() {
        console.log('❌ Disconnected from WebSocket server');
        isConnected = false;
        updateConnectionStatus('Disconnected', 'status-disconnected');
        showNotification('Disconnected from server', 'error');
        
        // Attempt reconnection after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
        showNotification('WebSocket error. Check if server is running.', 'error');
    };
}

// Handle incoming WebSocket messages
function handleWebSocketMessage(data) {
    const type = data.type || 'unknown';
    
    switch(type) {
        case 'traffic_update':
            handleTrafficUpdate(data.data);
            break;
            
        case 'agent_decision':
            handleAgentDecision(data);
            break;
            
        case 'communication':
            handleCommunicationEvent(data);
            break;
            
        case 'metrics':
            handleMetricsUpdate(data.data);
            break;
            
        case 'system':
            handleSystemMessage(data);
            break;
            
        case 'historical':
            handleHistoricalData(data.data);
            break;
            
        case 'pong':
            // Heartbeat response
            break;
            
        default:
            console.log('Unknown message type:', type, data);
    }
}

// Handle traffic update
function handleTrafficUpdate(stepData) {
    // Update global stats
    totalSteps.textContent = stepData.step;
    totalReward.textContent = stepData.total_reward.toFixed(2);
    vehicleCount.textContent = stepData.vehicles;
    avgSpeed.textContent = stepData.avg_speed.toFixed(1);
    
    // Store in history
    stepHistory.push({
        timestamp: stepData.timestamp,
        step: stepData.step,
        reward: stepData.reward,
        vehicles: stepData.vehicles,
        speed: stepData.avg_speed
    });
    
    // Keep only last 500 steps
    if (stepHistory.length > 500) {
        stepHistory.shift();
    }
    
    // Update current actions display
    updateCurrentActions(stepData.agents);
    
    // Update agent panels
    updateAgentPanels(stepData.agents);
    
    // Update charts
    updateCharts();
}

// Update current actions display
function updateCurrentActions(agentsData) {
    let html = '';
    
    for (const [agentId, agentData] of Object.entries(agentsData)) {
        const actionName = agentData.action_name || ACTION_NAMES[agentData.action] || 'UNKNOWN';
        const actionColor = agentData.action_color || ACTION_COLORS[agentData.action] || '#666';
        
        html += `
            <div style="margin-bottom: 15px; padding: 10px; background: #f8f9fa; border-radius: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: #2c3e50;">${agentId}</strong>
                    <span style="padding: 5px 12px; border-radius: 15px; background: ${actionColor}; color: white; font-size: 12px; font-weight: bold;">
                        ${actionName}
                    </span>
                </div>
                <div style="margin-top: 8px; font-size: 12px; color: #7f8c8d;">
                    Phase: ${agentData.phase_duration.toFixed(1)}s
                </div>
            </div>
        `;
    }
    
    currentActions.innerHTML = html || '<p class="no-data">No agent data</p>';
}

// Update agent panels
function updateAgentPanels(agentsData) {
    let html = '';
    
    for (const [agentId, agentData] of Object.entries(agentsData)) {
        // Initialize agent if not exists
        if (!agents[agentId]) {
            agents[agentId] = {
                queueHistory: [],
                waitHistory: [],
                actionHistory: []
            };
        }
        
        // Store history
        agents[agentId].queueHistory.push({
            timestamp: Date.now(),
            queues: agentData.queues
        });
        
        if (agents[agentId].queueHistory.length > 50) {
            agents[agentId].queueHistory.shift();
        }
        
        const actionColor = agentData.action_color || ACTION_COLORS[agentData.action] || '#666';
        const actionName = agentData.action_name || ACTION_NAMES[agentData.action] || 'UNKNOWN';
        
        // Queue bars HTML
        let queueBars = '';
        agentData.queues.forEach((queue, index) => {
            const percentage = Math.min((queue / 20) * 100, 100);
            const color = queue > 15 ? '#e74c3c' : queue > 10 ? '#f39c12' : queue > 5 ? '#27ae60' : '#3498db';
            
            queueBars += `
                <div class="queue-item">
                    <div class="direction-label">${DIRECTION_LABELS[index]}</div>
                    <div class="queue-bar">
                        <div class="queue-fill" style="width: ${percentage}%; background: ${color};"></div>
                    </div>
                    <div class="queue-value">${queue.toFixed(1)}</div>
                </div>
            `;
        });
        
        // Average wait times
        const avgWait = agentData.waits.reduce((a, b) => a + b, 0) / agentData.waits.length;
        
        html += `
            <div class="agent-card">
                <div class="agent-header">
                    <div class="agent-name">${agentId}</div>
                    <div class="agent-action" style="background: ${actionColor};">${actionName}</div>
                </div>
                
                <div class="queue-display">
                    ${queueBars}
                </div>
                
                <div style="font-size: 12px; color: #7f8c8d; margin-top: 10px;">
                    <div>Avg Wait: ${avgWait.toFixed(1)}s</div>
                    <div>Current Green: ${DIRECTION_LABELS[agentData.current_green] || 'None'}</div>
                </div>
            </div>
        `;
    }
    
    agentPanels.innerHTML = html || '<p style="grid-column: span 2; text-align: center; color: #7f8c8d;">No agent data available</p>';
}

// Handle agent decision
function handleAgentDecision(data) {
    const agentId = data.agent_id;
    const action = data.action;
    const actionName = ACTION_NAMES[action] || 'UNKNOWN';
    const actionColor = ACTION_COLORS[action] || '#666';
    
    // Add to communication log
    addToCommunicationLog({
        timestamp: new Date(data.timestamp * 1000),
        type: 'decision',
        agent: agentId,
        message: `${agentId} chose ${actionName}`,
        reasoning: data.reasoning || '',
        color: actionColor
    });
}

// Handle communication event
function handleCommunicationEvent(data) {
    addToCommunicationLog({
        timestamp: new Date(data.timestamp * 1000),
        type: 'communication',
        from: data.from,
        to: data.to,
        message: `Message from ${data.from} to ${data.to}`,
        details: data.message,
        color: '#9b59b6'
    });
}

// Handle metrics update
function handleMetricsUpdate(metrics) {
    // Update any metric-specific displays
    console.log('Metrics update:', metrics);
}

// Handle system messages
function handleSystemMessage(data) {
    const subtype = data.subtype || 'message';
    
    switch(subtype) {
        case 'welcome':
            showNotification(data.message, 'success');
            break;
            
        case 'status_update':
            showNotification(data.message, 'info');
            break;
            
        case 'shutting_down':
            showNotification(data.message, 'warning');
            break;
    }
}

// Handle historical data
function handleHistoricalData(history) {
    console.log(`Received ${history.length} historical data points`);
    // Could use this to initialize charts with past data
}

// Add entry to communication log
function addToCommunicationLog(entry) {
    communicationLog.unshift(entry);
    
    // Keep only last 50 entries
    if (communicationLog.length > 50) {
        communicationLog.pop();
    }
    
    // Update display
    updateCommunicationLog();
}

// Update communication log display
function updateCommunicationLog() {
    let html = '';
    
    communicationLog.forEach(entry => {
        const timeStr = entry.timestamp.toLocaleTimeString([], { 
            hour: '2-digit', 
            minute: '2-digit',
            second: '2-digit'
        });
        
        html += `
            <div class="log-entry" style="border-left-color: ${entry.color}">
                <div class="log-timestamp">${timeStr}</div>
                <div class="log-message">
                    <strong>${entry.message}</strong>
                    ${entry.reasoning ? `<div style="margin-top: 5px; font-size: 12px; color: #7f8c8d;">${entry.reasoning}</div>` : ''}
                    ${entry.details ? `<div style="margin-top: 5px; font-size: 12px; color: #666;">${JSON.stringify(entry.details)}</div>` : ''}
                </div>
            </div>
        `;
    });
    
    communicationLogDiv.innerHTML = html || '<div class="log-entry">No communication data yet</div>';
}

// Initialize charts
function initializeCharts() {
    // Queue Chart
    const queueCtx = document.getElementById('queueChart').getContext('2d');
    charts.queue = new Chart(queueCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: []
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                title: {
                    display: true,
                    text: 'Queue Lengths Over Time'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Queue Length'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Step'
                    }
                }
            }
        }
    });
    
    // Reward Chart
    const rewardCtx = document.getElementById('rewardChart').getContext('2d');
    charts.reward = new Chart(rewardCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Reward',
                data: [],
                borderColor: '#3498db',
                backgroundColor: 'rgba(52, 152, 219, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                title: {
                    display: true,
                    text: 'Reward History'
                }
            },
            scales: {
                y: {
                    title: {
                        display: true,
                        text: 'Reward'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: 'Step'
                    }
                }
            }
        }
    });
}

// Update charts
function updateCharts() {
    if (!charts.queue || !charts.reward) return;
    
    // Update reward chart
    if (stepHistory.length > 0) {
        const recentSteps = stepHistory.slice(-50);
        charts.reward.data.labels = recentSteps.map(s => s.step);
        charts.reward.data.datasets[0].data = recentSteps.map(s => s.reward);
        charts.reward.update();
    }
    
    // Update queue chart if we have agent data
    if (Object.keys(agents).length > 0) {
        const agentIds = Object.keys(agents);
        const datasets = [];
        
        agentIds.forEach((agentId, agentIndex) => {
            const agent = agents[agentId];
            if (agent.queueHistory.length > 0) {
                const recentQueues = agent.queueHistory.slice(-50);
                
                // Add dataset for each direction
                DIRECTION_LABELS.forEach((direction, dirIndex) => {
                    const color = dirIndex === 0 ? '#FF6B6B' : 
                                  dirIndex === 1 ? '#4ECDC4' : 
                                  dirIndex === 2 ? '#FFD166' : '#06D6A0';
                    
                    datasets.push({
                        label: `${agentId} - ${direction}`,
                        data: recentQueues.map(q => q.queues[dirIndex]),
                        borderColor: color,
                        backgroundColor: color + '20',
                        borderWidth: 1,
                        tension: 0.4,
                        pointRadius: 0
                    });
                });
            }
        });
        
        if (datasets.length > 0) {
            charts.queue.data.labels = Array.from({length: 50}, (_, i) => i);
            charts.queue.data.datasets = datasets.slice(0, 8); // Limit to 8 datasets for clarity
            charts.queue.update();
        }
    }
}

// Update connection status
function updateConnectionStatus(text, className) {
    connectionStatus.textContent = text;
    connectionStatus.className = 'status-badge ' + className;
}

// Show notification
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        background: ${type === 'success' ? '#2ecc71' : type === 'error' ? '#e74c3c' : '#3498db'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    notification.textContent = message;
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
    
    .no-data {
        color: #7f8c8d;
        text-align: center;
        font-style: italic;
        padding: 20px;
    }
`;
document.head.appendChild(style);

// Initialize dashboard
function initDashboard() {
    console.log('Initializing MARL Traffic Control Dashboard...');
    
    // Initialize charts
    initializeCharts();
    
    // Connect to WebSocket
    connectWebSocket();
    
    // Set up periodic updates
    setInterval(() => {
        if (isConnected && ws && ws.readyState === WebSocket.OPEN) {
            // Send ping to keep connection alive
            ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
        }
    }, 30000); // Every 30 seconds
    
    // Update charts periodically
    setInterval(updateCharts, 1000);
    
    console.log('Dashboard initialized. Waiting for data...');
}

// Start dashboard when page loads
window.addEventListener('load', initDashboard);