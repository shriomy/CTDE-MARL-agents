#!/usr/bin/env python3
"""
Generate 3-junction SUMO network:
- J1: 2-way junction (North-South) with pedestrian crossing
- J2: 3-way junction (Y-shaped)
- J3: 4-way junction (existing style)
"""

import os
import subprocess
import sys

def generate_3junction_network():
    """Generate the 3-junction network using SUMO netconvert"""
    
    # Project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    sumo_configs = os.path.join(project_root, "sumo_configs")
    
    # File paths
    nodes_file = os.path.join(sumo_configs, "nodes_3junctions.xml")
    edges_file = os.path.join(sumo_configs, "edges_3junctions.xml")
    output_net = os.path.join(sumo_configs, "3junctions.net.xml")
    
    # Verify input files exist
    if not os.path.exists(nodes_file):
        print(f"❌ ERROR: nodes_3junctions.xml not found at {nodes_file}")
        return False
    
    if not os.path.exists(edges_file):
        print(f"❌ ERROR: edges_3junctions.xml not found at {edges_file}")
        return False
    
    # Run netconvert
    print("🔄 Generating 3-junction network...")
    print(f"   Nodes file: {nodes_file}")
    print(f"   Edges file: {edges_file}")
    print(f"   Output net: {output_net}")
    
    try:
        cmd = [
            "netconvert",
            "--node-files", nodes_file,
            "--edge-files", edges_file,
            "--output-file", output_net,
            "--lefthand",  # Left-hand traffic (driving on left side)
            "--no-turnarounds",  # No illegal turns
            "--junctions.join",  # Join junctions
            "--tls.guess",  # Auto-generate traffic lights
            "--tls.set", "J1_2way,J2_3way,J3_4way",  # Set traffic light junctions
            "--verbose"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"❌ netconvert failed with return code {result.returncode}")
            print(f"\nStdout:\n{result.stdout}")
            print(f"\nStderr:\n{result.stderr}")
            return False
        
        if os.path.exists(output_net):
            print(f"✅ Network successfully generated: {output_net}")
            print(f"   File size: {os.path.getsize(output_net)} bytes")
            return True
        else:
            print(f"❌ Output file not created: {output_net}")
            return False
            
    except FileNotFoundError:
        print("❌ ERROR: netconvert not found in PATH")
        print("   Make sure SUMO is installed and netconvert is in your PATH")
        return False
    except subprocess.TimeoutExpired:
        print("❌ ERROR: netconvert timed out")
        return False
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    success = generate_3junction_network()
    sys.exit(0 if success else 1)
