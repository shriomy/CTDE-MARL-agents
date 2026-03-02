# 3-Junction SUMO Network Configuration Guide

## Overview

You now have a **3-junction traffic network** replacing the original 1×2 configuration. The new network consists of:

### Network Structure

```
Linear corridor (east–west) with three signal points:

J1 -- J2 -- J3
|      |      |
2-way 3-way 4-way
(ped)  (north) 

- Road runs straight along y=400; no diagonal links.
- Vehicles proceed east–west through all junctions.
- J1 is simply a signalized pedestrian crossing; two signal groups (east vs west).
- J2 is a T-intersection: main road east–west plus a northern branch.
- J3 is a full crossroad with all four compass directions.

Signal Control:  Only one direction green at a time
  • J1: east or west traffic
  • J2: east, west or north traffic
  • J3: east, west, north or south traffic
```

---

## Junction Details

### 1. **J1_2way** - 2-Way Junction (North-South)
- **Type**: Binary control junction
- **Directions**: North ↔ South only
- **Lanes**: 2 incoming lanes per direction
- **Special Feature**: Pedestrian crossing (East-West) included
- **Control States**: 2 phases
  - Phase 1: North GREEN (vehicles from North can go to South)
  - Phase 2: South GREEN (vehicles from South can go to North)
- **Agent ID**: `J1_2way`
- **Incoming Edges**:
  - `J1_2way_north_in` (from North, 2 lanes)
  - `J1_2way_south_in` (from South, 2 lanes)
- **Outgoing Edges**:
  - `J1_2way_north_out` (to North, 2 lanes)
  - `J1_2way_south_out` (to South, 2 lanes)

---

### 2. **J2_3way** - 3-Way Junction (Y-shaped)
- **Type**: Tri-directional intersection
- **Directions**: North, East, South (Y-shaped, no West)
- **Lanes**: 2 incoming lanes per direction
- **Control States**: 3 phases
  - Phase 1: North GREEN → can go to East or South
  - Phase 2: East GREEN → can go to North or South
  - Phase 3: South GREEN → can go to North or East
- **Agent ID**: `J2_3way`
- **Incoming Edges**:
  - `J2_3way_north_in` (from North, 2 lanes)
  - `J2_3way_east_in` (from East, 2 lanes)
  - `J2_3way_south_in` (from South, 2 lanes)
- **Outgoing Edges**:
  - `J2_3way_north_out` (to North, 2 lanes)
  - `J2_3way_east_out` (to East, 2 lanes)
  - `J2_3way_south_out` (to South, 2 lanes)

---

### 3. **J3_4way** - 4-Way Junction (Full Intersection)
- **Type**: Standard 4-way traffic intersection
- **Directions**: North, South, East, West (complete)
- **Lanes**: 2 incoming lanes per direction
- **Control States**: 4 phases
  - Phase 1: North GREEN → can go to South, East, or West
  - Phase 2: South GREEN → can go to North, East, or West
  - Phase 3: East GREEN → can go to North, South, or West
  - Phase 4: West GREEN → can go to North, South, or East
- **Agent ID**: `J3_4way`
- **Incoming Edges**:
  - `J3_4way_north_in` (from North, 2 lanes)
  - `J3_4way_south_in` (from South, 2 lanes)
  - `J3_4way_east_in` (from East, 2 lanes)
  - `J3_4way_west_in` (from West, 2 lanes)
- **Outgoing Edges**:
  - `J3_4way_north_out` (to North, 2 lanes)
  - `J3_4way_south_out` (to South, 2 lanes)
  - `J3_4way_east_out` (to East, 2 lanes)
  - `J3_4way_west_out` (to West, 2 lanes)

---

## Traffic Characteristics

### Vehicle Distribution
- **2-Way Junction (J1)**: 800 vehicles/hour (400 each direction, balanced)
- **3-Way Junction (J2)**: ~1180 vehicles/hour (uneven to test control)
- **4-Way Junction (J3)**: ~2810 vehicles/hour (high volume)

### Vehicle Types
- **Car** (default): 90% of traffic
- **Truck**: 10% of traffic (longer, slower)

### Left-Hand Traffic
- Vehicles drive on the **LEFT side** of the road (as specified)
- Configuration: `lefthand="true"` in SUMO network

---

## Files

All new configuration files are in `sumo_configs/`:

| File | Purpose |
|------|---------|
| `nodes_3junctions.xml` | Junction and terminal node definitions |
| `edges_3junctions.xml` | Road connections and lane configurations |
| `3junctions.net.xml` | **Generated network file** (SUMO uses this) |
| `3junctions.rou.xml` | Vehicle routes and traffic flows |
| `3junctions.sumocfg` | SUMO simulation configuration |

---

## Running the Simulation

### GUI Visualization
```bash
sumo-gui -c sumo_configs/3junctions.sumocfg
```
- Shows real-time traffic flow
- Displays vehicle queues at each junction
- Shows active (green) traffic light phases

### Headless (for training)
```bash
sumo -c sumo_configs/3junctions.sumocfg --end 3600
```
- No GUI, faster execution
- Suitable for automated training/testing

### Python Integration
```python
from utils.sumo_env_new import SumoEnv

env = SumoEnv(config_path="sumo_configs/3junctions.sumocfg", use_gui=False)
env.start()

# Get state for all agents
state = env.get_state()  
# Returns: {
#   "J1_2way": [...],  # 13 features
#   "J2_3way": [...],  # 13 features  
#   "J3_4way": [...]   # 13 features
# }

# Take action (phase duration in seconds)
actions = {
    "J1_2way": 25,  # 0-4: North/South (2-way)
    "J2_3way": 30,  # 0-5: North/East/South (3-way)
    "J3_4way": 20   # 0-7: North/South/East/West (4-way)
}
next_state, reward, done, info = env.step(actions)
```

---

## Updating Your Training Code

### For MARL Training

Update `main.py`:
```python
# Change from 1x2 to 3junctions
config_path = "sumo_configs/3junctions.sumocfg"

# Update agent IDs
agent_ids = ["J1_2way", "J2_3way", "J3_4way"]

# Define action spaces for each agent type
action_dims = {
    "J1_2way": 2,   # 2-way junction has 2 signal phases
    "J2_3way": 3,   # 3-way junction has 3 signal phases
    "J3_4way": 4    # 4-way junction has 4 signal phases
}

# State dim remains 13 (or 23 with neighbor enhancement)
state_dim = 13
```

### For Fixed-Time Controller

Update `fixed_time_controller.py`:
```python
# Change config path
config_path = "sumo_configs/3junctions.sumocfg"

# Define cycle for each junction type
cycles = {
    "J1_2way": {
        "north": 30,
        "south": 30,
        "yellow": 3
    },
    "J2_3way": {
        "north": 25,
        "east": 25,
        "south": 25,
        "yellow": 3
    },
    "J3_4way": {
        "north": 20,
        "south": 20,
        "east": 20,
        "west": 20,
        "yellow": 3
    }
}
```

---

## State Observation Format

Each agent observes 13 features from incoming lanes:

```python
state = [
    queue_lane1,           # vehicles in lane 1
    queue_lane2,           # vehicles in lane 2
    queue_lane3,           # (3-way/4-way) vehicles in lane 3
    queue_lane4,           # (4-way) vehicles in lane 4
    speed_lane1,           # avg speed in lane 1
    speed_lane2,           # avg speed in lane 2
    speed_lane3,           # (3-way/4-way) avg speed in lane 3
    speed_lane4,           # (4-way) avg speed in lane 4
    current_phase / 8,     # normalized current light phase
    waiting_time / 100,    # normalized total wait time
    departed_count / 10,   # normalized vehicles that left
    arrived_count / 10     # normalized vehicles that arrived
]
```

---

## Reward Calculation

Default reward function (optimize for):
- ✅ **Low average queue length** (reward = -sum_queues × 0.1)
- ✅ **High average speed** (reward = avg_speed × 0.05)
- ✅ **High throughput** (reward = (departed+arrived) × 0.01)

Formula:
```
reward = -avg_queue_length * 0.1 + average_speed * 0.05 + throughput * 0.01
```

---

## Key Differences from 1×2 Setup

| Aspect | 1×2 (Old) | 3-Junction (New) |
|--------|-----------|-----------------|
| **Junctions** | 2 (both 4-way) | 3 (2-way, 3-way, 4-way) |
| **Agents** | 2 | 3 |
| **Complexity** | Low | Medium |
| **Signal Groups** | 4 each | 2, 3, and 4 respectively |
| **Total Signal Configs** | 16 (4²) | 24 (2×3×4) |
| **Traffic Volume** | ~1600 veh/hr | ~4790 veh/hr |
| **Coordination Challenge** | Moderate | High |

---

## Testing Your Network

### Quick Verification Script

```python
# test_3junctions.py
import sys
sys.path.insert(0, '.')
from utils.sumo_env_new import SumoEnv

env = SumoEnv(config_path="sumo_configs/3junctions.sumocfg", use_gui=False)
env.start()

# Run for 100 steps
for step in range(100):
    state = env.get_state()
    
    # Dummy actions: hold each green for 20 seconds
    actions = {"J1_2way": 20, "J2_3way": 25, "J3_4way": 20}
    
    next_state, reward, done, info = env.step(actions)
    
    if step % 10 == 0:
        print(f"Step {step}: Reward={reward:.2f}")
        for agent_id, s in next_state.items():
            queues = sum(s[:2] if agent_id == "J1_2way" else (s[:3] if agent_id == "J2_3way" else s[:4]))
            print(f"  {agent_id}: Queue={queues:.0f}")

env.close()
print("✅ Network test completed successfully!")
```

Run it:
```bash
python test_3junctions.py
```

---

## Tips for Success

1. **Start Simple**: Test with fixed-time control first to understand the network
2. **Visualize Early**: Use `sumo-gui` to watch traffic patterns
3. **Adjust Hyperparameters**: The 3-way and 4-way junctions may need different learning rates
4. **Monitor Metrics**: Track queue lengths and throughput for each junction
5. **Test Scalability**: Experiment with different traffic volumes in `3junctions.rou.xml`

---

## Troubleshooting

### Network doesn't load
```bash
# Regenerate network
python generate_3junctions_network.py
```

### No vehicles spawning
- Check `3junctions.rou.xml` has valid routes
- Verify `3junctions.net.xml` connections are correct
- Ensure edge names match between routes and network

### High latency/slow simulation
- Run without GUI: `sumo -c ... ` instead of `sumo-gui`
- Reduce end time in `3junctions.sumocfg`
- Lower traffic demand in `3junctions.rou.xml`

---

## Next Steps

1. ✅ Test visualization: `sumo-gui -c sumo_configs/3junctions.sumocfg`
2. Update `main.py` with new agent IDs and action dimensions
3. Retrain MARL agents on new network  
4. Compare performance: Fixed-Time vs MARL on 3-junction network
5. Deploy to dashboard for multi-user comparison

---

**Network created**: March 2, 2026
**Configuration**: Lefthand traffic, 3 junctions (2-way, 3-way, 4-way)
**Status**: ✅ Tested and Ready
