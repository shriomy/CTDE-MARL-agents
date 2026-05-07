# Emergency Vehicle Handling & Agent Training Guide

## Overview

The improved scenarios now include emergency vehicles in ALL scenarios (not just dedicated emergency scenarios). This requires the agent to learn dynamic, multi-objective signal control:

1. **Optimize normal traffic flow** (vehicle throughput, wait times)
2. **Prioritize emergency vehicles** (immediate green when detected)
3. **Manage pedestrians** (especially mobility-aided users)
4. **Avoid gridlock** (balance competing objectives)

---

## Signal Control Logic for Emergency Vehicles

### Core Rule
**When an emergency vehicle is detected approaching an intersection, immediately give it a green light until it completely clears.**

### Implementation Pseudocode

```python
def signal_control_logic(state):
    """
    State includes:
    - Queue lengths on each lane
    - Traffic light status
    - Emergency vehicle positions & velocities
    - Pedestrian counts
    - Wait times for pedestrians/vehicles
    """
    
    # PRIORITY 1: EMERGENCY VEHICLE DETECTION
    emergency_vehicles_approaching = detect_emergency_vehicles(state)
    
    if emergency_vehicles_approaching:
        emergency_lanes = get_lanes_with_emergency(emergency_vehicles_approaching)
        
        for lane in emergency_lanes:
            # Keep green until emergency clears
            if not emergency_vehicle_cleared(lane):
                signal[lane] = GREEN  # MANDATORY
                signal[opposing_lanes] = RED
                pedestrian_signal[crossing] = RED  # Block pedestrians during emergency
                
                # Override all other logic
                continue_until_emergency_clears(lane)
                return signal
    
    # PRIORITY 2: HIGH PEDESTRIAN PRIORITY (Mobility-aided)
    if high_priority_pedestrians_waiting(state):
        # Allow pedestrian crossing with shorter wait
        signal = optimize_pedestrian_crossing(state, priority=HIGH)
    
    # PRIORITY 3: NORMAL TRAFFIC OPTIMIZATION
    else:
        signal = optimize_vehicle_throughput(state)
    
    return signal
```

### Enhanced State Representation

The agent needs to observe:

```python
class TrafficState:
    # Lane information
    queue_lengths: Dict[Lane, int]           # Vehicles waiting in each lane
    vehicle_wait_times: Dict[Lane, float]    # Average wait time
    
    # Emergency vehicle information (NEW)
    emergency_vehicles: List[EmergencyVehicle]
    emergency_vehicles_approaching: Dict[Lane, float]  # Distance to intersection
    emergency_vehicle_type: Dict[Lane, str]  # ambulance/police/firetruck
    
    # Pedestrian information
    pedestrian_queues: Dict[Crossing, List[Pedestrian]]
    pedestrian_types: Dict[Pedestrian, str]  # adult/elder/student/mobility_aid
    pedestrian_wait_times: Dict[Crossing, float]
    
    # Signal state
    current_signal_phase: int
    time_in_phase: float
    
    # Timing information
    episode_time: float
    time_since_last_signal_change: float
```

---

## Scenario-Specific Training Focus

### S01: Route Coverage (Episodes 1-5)
**Goal**: Learn intersection geometry and basic signal timing
- Moderate traffic with even distribution
- Minimal emergencies (5-15)
- Few pedestrians (15-40)
- **Focus**: Basic Q-learning on route patterns

### S04a-S04c: Emergency Introduction (Episodes 6-10)
**Goal**: Learn emergency detection and response
- **S04a**: Single emergency vehicle
- **S04b**: Multiple simultaneous emergencies
- **S04c**: Emergency + high pedestrian density

**Agent Must Learn**:
1. Detect emergency vehicle presence
2. Identify which lane(s) contain emergency
3. Give that lane green immediately
4. Maintain until emergency clears
5. Resume normal signaling

### S07a: Priority Stress (Episodes 11+)
**Goal**: Complex multi-objective optimization
- 18-30 emergency vehicles simultaneously
- 100-140+ pedestrians (50%+ mobility-aided)
- Heavy traffic (20-150 vph)

**Agent Must Balance**:
1. Emergency priority (HIGHEST)
2. Mobility-aided pedestrian priority (HIGH)
3. Normal pedestrian crossing (MEDIUM)
4. Vehicle throughput (MEDIUM)
5. Avoid gridlock (CRITICAL)

---

## Reward Function Design

### Recommended Multi-Objective Reward

```python
def calculate_reward(state, action):
    """
    Multi-objective reward considering all priorities.
    """
    
    # COMPONENT 1: Emergency Response (HIGHEST WEIGHT)
    emergency_penalty = -100 * time_emergency_waiting_at_red(state)  # If emergency blocked
    emergency_bonus = +50 * (1 / (emergency_arrival_time + 1))      # Quick response
    
    # COMPONENT 2: Pedestrian Waiting (HIGH WEIGHT)
    ped_wait_penalty = -5 * avg_pedestrian_wait_time(state)
    mobility_aid_penalty = -20 * avg_mobility_aid_wait_time(state)   # Double weight
    
    # COMPONENT 3: Vehicle Throughput (MEDIUM WEIGHT)
    throughput_reward = +2 * vehicles_cleared_this_step(state)
    vehicle_wait_penalty = -2 * avg_vehicle_wait_time(state)
    
    # COMPONENT 4: Stability (PREVENTS GRIDLOCK)
    gridlock_penalty = -100 if queue_exceeds_capacity(state) else 0
    oscillation_penalty = -5 * signal_change_frequency(state)  # Penalize flickering
    
    # COMPONENT 5: Safety (COLLISION AVOIDANCE)
    collision_penalty = -500 * collision_count(state)
    near_miss_penalty = -50 * near_miss_count(state)
    
    # Total reward
    total_reward = (
        emergency_penalty + emergency_bonus +           # 30% weight
        ped_wait_penalty + mobility_aid_penalty +       # 30% weight
        throughput_reward + vehicle_wait_penalty +      # 20% weight
        gridlock_penalty + oscillation_penalty +        # 15% weight
        collision_penalty + near_miss_penalty           # 5% weight
    )
    
    return total_reward
```

### Weight Priority
```
1. Safety (Collisions, Emergency response):        35%
2. Pedestrian equity (Especially mobility-aided):  35%
3. Vehicle throughput & wait times:                20%
4. Signal stability:                               10%
```

---

## Emergency Vehicle Detection Methods

### Method 1: Distance-Based Detection
```python
def detect_emergency_approaching(state, detection_range=200):
    """
    Detect if emergency vehicle is within X meters of intersection.
    """
    emergency_vehicles = []
    for vehicle in state.active_vehicles:
        if vehicle.is_emergency():
            distance_to_intersection = calculate_distance(vehicle, intersection)
            if distance_to_intersection < detection_range:
                emergency_vehicles.append(vehicle)
    return emergency_vehicles
```

### Method 2: SUMO Simulation Access
```python
def get_emergency_vehicles_sumo(sumo_client):
    """
    Direct query to SUMO for all emergency vehicles.
    """
    emergency_vehicles = []
    
    # In SUMO API
    for vehicle_id in sumo_client.vehicle.getIDList():
        vtype = sumo_client.vehicle.getTypeID(vehicle_id)
        
        if vtype in ['ambulance', 'police', 'firetruck']:
            position = sumo_client.vehicle.getPosition(vehicle_id)
            position3d = sumo_client.vehicle.getPosition3D(vehicle_id)
            road_id = sumo_client.vehicle.getRoadID(vehicle_id)
            
            emergency_vehicles.append({
                'id': vehicle_id,
                'type': vtype,
                'position': position,
                'road': road_id,
                'speed': sumo_client.vehicle.getSpeed(vehicle_id),
                'route': sumo_client.vehicle.getRoute(vehicle_id)
            })
    
    return emergency_vehicles
```

### Method 3: Lane Occupancy Observation
```python
def detect_emergency_by_lane_detection(state):
    """
    If agent doesn't have direct access, look at lane observations.
    High-speed vehicles entering intersection from certain direction.
    """
    emergency_detected = {}
    
    for lane in state.all_lanes:
        vehicles_on_lane = state.get_vehicles_on_lane(lane)
        
        for vehicle in vehicles_on_lane:
            if vehicle.speed > EMERGENCY_SPEED_THRESHOLD:  # e.g., >20 m/s
                if vehicle.time_on_lane < QUICK_CROSSING_TIME:
                    # Likely emergency (fast, quick passage)
                    emergency_detected[lane] = True
    
    return emergency_detected
```

---

## Agent Architecture for Emergency Response

### Option 1: Hierarchical Control
```
Top Level: Emergency Detection & Response
├─ Is emergency present? → YES: Route to emergency handler
│  └─ Emergency Handler: Keep lane green until cleared
└─ NO: Continue normal control
    └─ Second Level: Pedestrian Priority Check
       ├─ High priority pedestrians? → YES: Pedestrian phase
       └─ NO: Vehicle optimization phase
```

### Option 2: Attention-Based Architecture
```
Input Encoding:
├─ Emergency vehicle attention layer (weights emergency features highly)
├─ Pedestrian attention layer (weights pedestrian types by priority)
└─ Lane congestion attention layer

Output:
├─ Signal phase decision
└─ Time in phase decision
```

### Option 3: Rule-Based + Learning
```
IF emergency_present THEN
    SET signal to give emergency lane GREEN
ELSE IF high_pedestrian_density THEN
    USE learned policy for pedestrian priority
ELSE
    USE learned policy for normal optimization
```

---

## Training Progression

### Stage 1: Baseline (Episodes 1-30)
- Use S01-S03 (route coverage, light/heavy traffic)
- Minimal emergencies (3-15 per episode)
- Learn basic intersection dynamics
- Expected: Vehicle wait ~30-45s, pedestrian wait ~40-60s

### Stage 2: Emergency Introduction (Episodes 31-100)
- Gradually introduce emergencies
- Use S04a, S04b, S04c with increasing frequency
- Agent learns emergency detection
- Expected: Emergency response within 5 seconds

### Stage 3: Mixed Training (Episodes 101-500)
- Random scenario selection
- Includes all scenario types proportionally
- Agent learns to balance competing objectives
- Expected: Smooth transitions between phases

### Stage 4: Stress Testing (Episodes 501+)
- Use S07a (Priority Stress) frequently
- Maximum complexity: all elements active
- Validates robustness under stress
- Expected: Maintains safety while optimizing

---

## Performance Baselines

### Good Performance Metrics

| Metric | Light Traffic | Normal Traffic | Heavy Traffic | Emergency |
|--------|---------------|----------------|---------------|-----------|
| Avg Vehicle Wait | 15-25s | 25-45s | 35-65s | <5s priority |
| Avg Pedestrian Wait | 30-45s | 40-60s | 50-80s | <10s if waiting |
| Mobility-aid Wait | 40-60s | 60-90s | 80-120s | <15s priority |
| Emergency Response | <2s | <3s | <5s | CRITICAL |
| Collisions | 0 | 0 | 0 | 0 |
| Throughput (veh/min) | 20-30 | 15-25 | 10-20 | N/A |

---

## Testing Checklist

- [ ] Emergency vehicle appears in agent's observation
- [ ] Agent gives green light to emergency lane immediately
- [ ] Other lanes turn red when emergency approaches
- [ ] Pedestrian signals show red during emergency passage
- [ ] Agent maintains green until emergency clears
- [ ] Agent returns to normal signaling after emergency passes
- [ ] Mobility-aided pedestrians get shorter wait times
- [ ] No collisions between vehicles and pedestrians
- [ ] Normal traffic continues even with emergencies present
- [ ] Multiple simultaneous emergencies handled correctly

---

## Expected Learning Curve

```
Performance
    ^
    |     ╱╲ S07a Challenge
    |    ╱  ╲
    |   ╱    ╲___
    |  ╱         ╲____╱╲ Convergence
    | ╱ S04 Intro      ╲╱
    |╱_________________ Plateau
    └─────────────────────────→ Episodes
    0  30  100  200  500  1000
```

**Key Phases**:
- Eps 0-30: Learning (0-30% of optimal)
- Eps 30-100: Emergency intro (30-60%)
- Eps 100-500: Mixed training (60-85%)
- Eps 500+: Convergence (85%+ of optimal)

---

## Common Agent Mistakes & Fixes

### Mistake 1: Emergency Ignored (Still Optimizing for Vehicles)
```
Symptoms: Emergency waits at red light
Fix: Increase emergency penalty weight in reward function
     Add explicit emergency detection layer
     Use supervised learning to bootstrap emergency behavior
```

### Mistake 2: Pedestrians Blocked Too Long
```
Symptoms: Pedestrian wait times > 120s in S05 scenarios
Fix: Increase pedestrian wait penalty
     Add explicit pedestrian priority mechanism
     Reduce vehicle phase duration
```

### Mistake 3: Signals Oscillating (Flickering)
```
Symptoms: Signal phase changes every 1-2 seconds
Fix: Add minimum phase duration constraint
     Add oscillation penalty to reward function
     Increase penalty for frequent signal changes
```

### Mistake 4: Gridlock (All Lanes Full)
```
Symptoms: Vehicle queues exceed road capacity
Fix: Increase gridlock penalty (e.g., -100 per gridlock event)
     Implement capacity tracking in state
     Add preventive green time before queues fill
```

---

## Advanced Training Techniques

### Curriculum Learning
```
Stage 1: Only light traffic (S02)
Stage 2: Add normal traffic (S01, S03)
Stage 3: Add single emergencies (S04a)
Stage 4: Add multiple emergencies (S04b)
Stage 5: Add emergency+pedestrian conflicts (S04c)
Stage 6: Add high pedestrian density (S05)
Stage 7: Add stress scenarios (S07)
```

### Transfer Learning
```
1. Pre-train on S01 (route coverage)
2. Fine-tune on S04 (emergencies)
3. Fine-tune on S05 (pedestrians)
4. Fine-tune on S07 (stress)
```

### Multi-Agent Coordination
```
Agents per junction: 3 (one per traffic light)
Shared training data from all scenarios
Reward for cross-intersection optimization
```

---

## Monitoring & Validation

### Key Metrics to Log

```python
metrics = {
    'episode': episode_num,
    'scenario': scenario_name,
    
    # Emergency metrics
    'avg_emergency_wait': float,
    'max_emergency_wait': float,
    'emergency_events': int,
    'emergency_response_time': float,
    
    # Pedestrian metrics
    'avg_pedestrian_wait': float,
    'max_pedestrian_wait': float,
    'avg_mobility_aid_wait': float,
    'pedestrian_events': int,
    
    # Vehicle metrics
    'avg_vehicle_wait': float,
    'throughput_vehicles_per_min': float,
    'queue_max_length': int,
    
    # Safety metrics
    'collision_count': int,
    'near_miss_count': int,
    
    # Efficiency metrics
    'episode_reward': float,
    'signal_phase_changes': int,
    'gridlock_events': int,
}
```

---

## References

- SUMO Emergency Vehicle Documentation
- Traffic Light Control Best Practices
- Multi-Objective Optimization in MARL
- Pedestrian Priority & ADA Compliance

---

**Version**: 2.0 | **Updated**: 2026-05-07 | **Status**: Ready for Implementation
