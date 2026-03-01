"""
Compare performance between MARL and Fixed-Time controllers.
"""
import os
import sys
import json
import numpy as np
from datetime import datetime

def load_marl_metrics(log_dir):
    """Load MARL execution metrics"""
    marl_logs = []
    for filename in os.listdir(log_dir):
        if filename.startswith("execution_") and filename.endswith(".json"):
            with open(os.path.join(log_dir, filename), 'r') as f:
                marl_logs.append(json.load(f))
    return marl_logs

def load_fixed_metrics(log_dir):
    """Load Fixed-Time execution metrics"""
    fixed_logs = []
    for filename in os.listdir(log_dir):
        if filename.startswith("fixed_time_") and filename.endswith(".json"):
            with open(os.path.join(log_dir, filename), 'r') as f:
                fixed_logs.append(json.load(f))
    return fixed_logs

def compare_performance():
    """Compare MARL vs Fixed-Time performance"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(project_root, "..", "logs")
    
    # Load metrics
    marl_logs = load_marl_metrics(os.path.join(logs_dir, "execution"))
    fixed_logs = load_fixed_metrics(os.path.join(logs_dir, "fixed_time"))
    
    if not marl_logs:
        print("⚠ No MARL execution logs found")
        return
    
    if not fixed_logs:
        print("⚠ No Fixed-Time execution logs found")
        return
    
    # Use most recent logs
    latest_marl = marl_logs[-1]
    latest_fixed = fixed_logs[-1]
    
    print("\n" + "="*60)
    print("PERFORMANCE COMPARISON: MARL vs FIXED-TIME")
    print("="*60)
    
    # MARL Metrics
    print("\n🤖 MARL (Multi-Agent Reinforcement Learning):")
    print(f"  Total Steps: {latest_marl.get('step', 'N/A')}")
    print(f"  Total Reward: {latest_marl.get('total_reward', 0):.2f}")
    
    if 'reward_history' in latest_marl and latest_marl['reward_history']:
        avg_reward = np.mean(latest_marl['reward_history'])
        std_reward = np.std(latest_marl['reward_history'])
        print(f"  Average Reward per Step: {avg_reward:.4f} (±{std_reward:.4f})")
    
    if 'queue_history' in latest_marl and latest_marl['queue_history']:
        avg_queue = np.mean(latest_marl['queue_history'])
        print(f"  Average Queue Length: {avg_queue:.1f}")
    
    if 'speed_history' in latest_marl and latest_marl['speed_history']:
        avg_speed = np.mean(latest_marl['speed_history'])
        print(f"  Average Speed: {avg_speed:.1f} m/s")
    
    # Fixed-Time Metrics
    print("\n⏱️ FIXED-TIME (Deterministic Cycle):")
    print(f"  Total Steps: {latest_fixed.get('total_steps', 'N/A')}")
    print(f"  Total Reward: {latest_fixed.get('total_reward', 0):.2f}")
    
    if 'reward_history' in latest_fixed and latest_fixed['reward_history']:
        avg_reward = np.mean(latest_fixed['reward_history'])
        std_reward = np.std(latest_fixed['reward_history'])
        print(f"  Average Reward per Step: {avg_reward:.4f} (±{std_reward:.4f})")
    
    if 'queue_history' in latest_fixed and latest_fixed['queue_history']:
        avg_queue = np.mean(latest_fixed['queue_history'])
        print(f"  Average Queue Length: {avg_queue:.1f}")
    
    if 'speed_history' in latest_fixed and latest_fixed['speed_history']:
        avg_speed = np.mean(latest_fixed['speed_history'])
        print(f"  Average Speed: {avg_speed:.1f} m/s")
    
    # Comparison
    print("\n📊 COMPARISON SUMMARY:")
    
    marl_reward = latest_marl.get('total_reward', 0)
    fixed_reward = latest_fixed.get('total_reward', 0)
    
    if marl_reward != 0 and fixed_reward != 0:
        improvement = ((marl_reward - fixed_reward) / abs(fixed_reward)) * 100
        print(f"  Reward Improvement: {improvement:+.1f}%")
        
        if improvement > 0:
            print(f"  ✅ MARL outperforms Fixed-Time by {improvement:.1f}%")
        else:
            print(f"  ❌ Fixed-Time outperforms MARL by {-improvement:.1f}%")
    
    print("\n" + "="*60)
    print("KEY INSIGHTS:")
    print("="*60)
    print("1. MARL adapts to traffic patterns")
    print("2. Fixed-Time uses predetermined cycle")
    print("3. MARL can coordinate between intersections")
    print("4. Fixed-Time is predictable but not adaptive")
    print("="*60)
    
    # Save comparison report
    comparison = {
        'timestamp': datetime.now().isoformat(),
        'marl': {
            'total_steps': latest_marl.get('step', 0),
            'total_reward': latest_marl.get('total_reward', 0),
            'avg_reward': np.mean(latest_marl.get('reward_history', [0])),
            'avg_queue': np.mean(latest_marl.get('queue_history', [0])),
            'avg_speed': np.mean(latest_marl.get('speed_history', [0]))
        },
        'fixed_time': {
            'total_steps': latest_fixed.get('total_steps', 0),
            'total_reward': latest_fixed.get('total_reward', 0),
            'avg_reward': np.mean(latest_fixed.get('reward_history', [0])),
            'avg_queue': np.mean(latest_fixed.get('queue_history', [0])),
            'avg_speed': np.mean(latest_fixed.get('speed_history', [0]))
        },
        'improvement_percentage': improvement if 'improvement' in locals() else 0
    }
    
    report_file = os.path.join(logs_dir, "comparison_report.json")
    with open(report_file, 'w') as f:
        json.dump(comparison, f, indent=2)
    
    print(f"\n📋 Comparison report saved to: {report_file}")

if __name__ == "__main__":
    compare_performance()