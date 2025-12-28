// MARL Traffic Control Dashboard JavaScript

// WebSocket connection
let ws = null;
let isConnected = false;
let agentData = {};
let updateHistory = [];
const MAX_HISTORY = 50;

// Chart instances
let queueChart = null;
let rewardChart = null;

// Action names mapping
const ACTION_NAMES = {
    0: "WEST",
    1: "NORTH",
    2: "EAST",
    3: "SOUTH",
    4: "EXTEND"
};

// Action colors
const ACTION_COLORS = {
    0: "#FF6B6B", // West - Red
    1: "#4ECDC4", // North - Teal
    2: "#FFD166", // East - Yellow
    3: "#06D6A0", // South - Green
    4: "#118AB2"  // Extend - Blue
};

// Initialize WebSocket connection
function connectWebSocket() {
    const wsUrl = 'ws://localhost:8765';
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = function() {
        console.log('Connected to MARL WebSocket server');
        isConnected = true;
        updateConnectionStatus('Connected', 'success');
        updateStatusMessage('Receiving real-time traffic data...');
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
        console.log('Disconnected from WebSocket server');
        isConnected = false;
        updateConnectionStatus('Disconnected', 'danger');
        updateStatusMessage('Connection lost. Attempting to reconnect in 5 seconds...');
        
        // Attempt reconnection after 5 seconds
        setTimeout(connectWebSocket, 5000);
    };
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
        updateStatusMessage('WebSocket error. Check if server is running.');
    };
}

// Handle incoming WebSocket messages
function handleWebSocketMessage(data) {
    switch(data.type) {
        case 'traffic_update':
            handleTrafficUpdate(data.data);
            break;
        case 'agent_decision':
            handleAgentDecision(data);
            break;
        case 'system_status':
            handleSystemStatus(data);
            break;
        case 'initial_data':
            handleInitialData(data.data);
            break;
        default:
            console.log('Unknown message type:', data.type);
    }
}

// Handle traffic update
function handleTrafficUpdate(stepData) {
    // Update step counter
    document.getElementById('current-step').textContent = stepData.step;
    document.getElementById('total-reward').textContent = stepData.total_reward.toFixed(2);
    document.getElementById('vehicle-count').textContent = stepData.vehicle_count;
    
    // Update agent panels
    for (const [agentId, action] of Object.entries(stepData.actions)) {
        if (!agentData[agentId]) {
            agentData[agentId] = {
                name: agentId,
                actions: [],
                queues: [],
                waits: []
            };
        }
        
        // Get queue data for this agent
        const queueKey = `${agentId}_queues`;
        const waitKey = `${agentId}_waits`;
        
        if (stepData[queueKey]) {
            agentData[agentId].queues = stepData[queueKey];
        }
        
        if (stepData[waitKey]) {
            agentData[agentId].waits = stepData[waitKey];
        }
        
        // Add action to history
        agentData[agentId].actions.unshift({
            step: stepData.step,
            action: action,
            timestamp: new Date().toLocaleTimeString()
        });
        
        // Keep only recent actions
        if (agentData[agentId].actions.length > 10) {
            agentData[agentId].actions.pop();
        }
        
        // Update agent panel
        updateAgentPanel(agentId);
    }
    
    // Add to update history
    addToUpdateHistory(stepData);
    
    // Update charts
    updateQueueChart();
}

// Handle agent decision
function handleAgentDecision(data) {
    const agentId = data.agent_id;
    const action = data.action;
    
    // Update agent's current action
    if (agentData[agentId]) {
        agentData[agentId].currentAction = action;
        agentData[agentId].currentState = data.state;
        updateAgentPanel(agentId);
    }
}

// Handle system status
function handleSystemStatus(data) {
    updateStatusMessage(data.message);
    
    // Update connection status based on system status
    if (data.status === 'shutdown') {
        updateConnectionStatus('Server Stopped', 'warning');
    }
}

// Handle initial data
function handleInitialData(initialData) {
    console.log('Received initial data:', initialData.length, 'data points');
    // You could use this to initialize charts with historical data
}

// Update agent panel in UI
function updateAgentPanel(agentId) {
    const agent = agentData[agentId];
    if (!agent) return;
    
    const panelId = `panel-${agentId}`;
    let panel = document.getElementById(panelId);
    
    if (!panel) {
        // Create new panel
        const panelsContainer = document.getElementById('agent-panels');
        panel = document.createElement('div');
        panel.id = panelId;
        panel.className = 'card mb-3';
        panel.innerHTML = `
            <div class="card-header">
                <h6 class="mb-0">${agentId}</h6>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-3">
                        <h6>Current Action</h6>
                        <span id="${agentId}-action" class="badge">Unknown</span>
                    </div>
                    <div class="col-md-9">
                        <h6>Queue Lengths</h6>
                        <div class="row">
                            <div class="col-3">
                                <small>West</small>
                                <div class="progress">
                                    <div id="${agentId}-west" class="progress-bar" style="width: 0%"></div>
                                </div>
                            </div>
                            <div class="col-3">
                                <small>North</small>
                                <div class="progress">
                                    <div id="${agentId}-north" class="progress-bar" style="width: 0%"></div>
                                </div>
                            </div>
                            <div class="col-3">
                                <small>East</small>
                                <div class="progress">
                                    <div id="${agentId}-east" class="progress-bar" style="width: 0%"></div>
                                </div>
                            </div>
                            <div class="col-3">
                                <small>South</small>
                                <div class="progress">
                                    <div id="${agentId}-south" class="progress-bar" style="width: 0%"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="mt-2">
                    <small>Recent Actions:</small>
                    <div id="${agentId}-action-history"></div>
                </div>
            </div>
        `;
        panelsContainer.appendChild(panel);
    }
    
    // Update current action
    const actionBadge = document.getElementById(`${agentId}-action`);
    if (agent.currentAction !== undefined) {
        const actionName = ACTION_NAMES[agent.currentAction] || 'UNKNOWN';
        const actionColor = ACTION_COLORS[agent.currentAction] || '#6c757d';
        actionBadge.textContent = actionName;
        actionBadge.className = 'badge';
        actionBadge.style.backgroundColor = actionColor;
    }
    
    // Update queue indicators
    const directions = ['west', 'north', 'east', 'south'];
    directions.forEach((dir, index) => {
        const queueValue = agent.queues[index] || 0;
        const maxQueue = 20; // Maximum queue for 100% width
        const percentage = Math.min((queueValue / maxQueue) * 100, 100);
        
        const bar = document.getElementById(`${agentId}-${dir}`);
        if (bar) {
            bar.style.width = `${percentage}%`;
            bar.textContent = Math.round(queueValue);
            
            // Color based on queue length
            if (queueValue > 15) bar.style.backgroundColor = '#dc3545';
            else if (queueValue > 10) bar.style.backgroundColor = '#ffc107';
            else if (queueValue > 5) bar.style.backgroundColor = '#28a745';
            else bar.style.backgroundColor = '#6c757d';
        }
    });
    
    // Update action history
    const historyContainer = document.getElementById(`${agentId}-action-history`);
    if (historyContainer) {
        historyContainer.innerHTML = agent.actions.slice(0, 5).map(a => 
            `<span class="badge bg-light text-dark me-1" title="Step ${a.step}">${ACTION_NAMES[a.action] || a.action}</span>`
        ).join('');
    }
}

// Add update to history table
function addToUpdateHistory(stepData) {
    const tableBody = document.getElementById('updates-table');
    
    // Create new row
    const row = document.createElement('tr');
    
    // Format timestamp
    const now = new Date();
    const timestamp = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    
    // For each agent, add a row
    Object.entries(stepData.actions).forEach(([agentId, action]) => {
        const queueKey = `${agentId}_queues`;
        const queues = stepData[queueKey] || [0, 0, 0, 0];
        
        row.innerHTML = `
            <td>${timestamp}</td>
            <td><strong>${agentId}</strong></td>
            <td><span class="badge" style="background-color: ${ACTION_COLORS[action] || '#6c757d'}">${ACTION_NAMES[action] || action}</span></td>
            <td>${queues[0].toFixed(1)}</td>
            <td>${queues[1].toFixed(1)}</td>
            <td>${queues[2].toFixed(1)}</td>
            <td>${queues[3].toFixed(1)}</td>
            <td>${stepData.reward.toFixed(2)}</td>
        `;
    });
    
    // Add to beginning of table
    tableBody.insertBefore(row, tableBody.firstChild);
    
    // Keep only recent rows
    while (tableBody.children.length > MAX_HISTORY) {
        tableBody.removeChild(tableBody.lastChild);
    }
}

// Update queue chart
function updateQueueChart() {
    const ctx = document.getElementById('queueChart').getContext('2d');
    
    if (!queueChart) {
        // Initialize chart
        queueChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
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
    }
    
    // Update chart data
    const steps = Array.from({length: 20}, (_, i) => i);
    const datasets = [];
    
    Object.entries(agentData).forEach(([agentId, data]) => {
        if (data.queues.length > 0) {
            datasets.push({
                label: `${agentId} - West`,
                data: steps.map(step => data.queues[0] || 0),
                borderColor: '#FF6B6B',
                backgroundColor: 'rgba(255, 107, 107, 0.1)',
                borderWidth: 2
            });
            
            datasets.push({
                label: `${agentId} - North`,
                data: steps.map(step => data.queues[1] || 0),
                borderColor: '#4ECDC4',
                backgroundColor: 'rgba(78, 205, 196, 0.1)',
                borderWidth: 2
            });
        }
    });
    
    queueChart.data.labels = steps;
    queueChart.data.datasets = datasets.slice(0, 4); // Limit to 4 datasets for clarity
    queueChart.update();
}

// Update connection status
function updateConnectionStatus(status, type) {
    const statusElement = document.getElementById('connection-status');
    statusElement.textContent = status;
    statusElement.className = `badge bg-${type}`;
}

// Update status message
function updateStatusMessage(message) {
    document.getElementById('status-message').textContent = message;
}

// Initialize dashboard
function initDashboard() {
    console.log('Initializing MARL Traffic Control Dashboard');
    
    // Connect to WebSocket
    connectWebSocket();
    
    // Set up periodic updates
    setInterval(() => {
        if (isConnected) {
            // Send heartbeat or request update
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'ping', timestamp: Date.now()}));
            }
        }
    }, 30000); // Every 30 seconds
    
    // Initial UI setup
    updateConnectionStatus('Connecting...', 'warning');
    updateStatusMessage('Attempting to connect to MARL execution server...');
}

// Start dashboard when page loads
window.addEventListener('load', initDashboard);