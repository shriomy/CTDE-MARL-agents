# Save as marl_execution/debug_executor.py
import os
import sys
import time

# Add paths
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, ".."))

print("="*60)
print("DEBUG: Testing imports and SUMO connection")
print("="*60)

# Test imports
try:
    print("1. Testing import of utils.sumo_env_new...")
    from utils.sumo_env_new import SumoEnv
    print("   ✓ Import successful")
except ImportError as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

try:
    print("\n2. Testing import of agents.multi_agent_system...")
    from agents.multi_agent_system import MultiAgentSystem
    print("   ✓ Import successful")
except ImportError as e:
    print(f"   ✗ Import failed: {e}")
    sys.exit(1)

# Test SUMO
print("\n3. Testing SUMO environment creation...")
try:
    config_path = os.path.join(project_root, "..", "sumo_configs", "1x2.sumocfg")
    print(f"   Config path: {config_path}")
    print(f"   File exists: {os.path.exists(config_path)}")
    
    print("\n   Creating SumoEnv object...")
    env = SumoEnv(config_path=config_path, use_gui=True)
    print("   ✓ SumoEnv created")
    
    print("\n   Starting SUMO (this may take a moment)...")
    env.start()
    print("   ✓ SUMO started!")
    
    print("\n4. Getting initial state...")
    state = env.get_state()
    print(f"   State keys: {list(state.keys())}")
    for key, value in state.items():
        print(f"   {key}: shape={value.shape}")
    
    print("\n5. Testing one step...")
    # Create dummy actions
    actions = {tl_id: 0 for tl_id in state.keys()}
    next_state, reward, done, info = env.step(actions)
    print(f"   Reward: {reward}")
    print(f"   Done: {done}")
    print(f"   Info: {info}")
    
    print("\n6. Closing SUMO...")
    env.close()
    print("   ✓ SUMO closed")
    
    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED!")
    print("="*60)
    
except Exception as e:
    print(f"\n✗ ERROR during test: {e}")
    import traceback
    traceback.print_exc()
    print("\n" + "="*60)
    print("TEST FAILED")
    print("="*60)