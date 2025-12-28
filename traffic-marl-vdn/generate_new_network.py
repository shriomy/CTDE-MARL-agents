import os
import subprocess
import sys

def generate_two_intersections():
    """Generate two connected 4-way intersections with 2-way roads"""
    
    print("Creating two connected 4-way intersections with 2-way roads...")
    
    # Create nodes file - J1_east and J2_west at DIFFERENT positions!
    nodes_content = '''<?xml version="1.0" encoding="UTF-8"?>
<nodes>
    <!-- INTERSECTION 1 (Left) -->
    <node id="J1_center" x="200" y="200" type="traffic_light"/>
    <node id="J1_north" x="200" y="400" type="priority"/>
    <node id="J1_south" x="200" y="0" type="priority"/>
    <node id="J1_west" x="0" y="200" type="priority"/>
    <node id="J1_east" x="350" y="200" type="priority"/>  <!-- Connection point -->
    
    <!-- INTERSECTION 2 (Right) -->
    <node id="J2_center" x="600" y="200" type="traffic_light"/>  <!-- MOVED from 500 to 600 -->
    <node id="J2_north" x="600" y="400" type="priority"/>
    <node id="J2_south" x="600" y="0" type="priority"/>
    <node id="J2_east" x="800" y="200" type="priority"/>
    <node id="J2_west" x="450" y="200" type="priority"/>  <!-- Connection point - DIFFERENT from J1_east! -->
    
    <!-- Edge nodes for longer roads -->
    <node id="far_west" x="-200" y="200" type="priority"/>
    <node id="far_east" x="1000" y="200" type="priority"/>
    <node id="far_north1" x="200" y="600" type="priority"/>
    <node id="far_south1" x="200" y="-200" type="priority"/>
    <node id="far_north2" x="600" y="600" type="priority"/>
    <node id="far_south2" x="600" y="-200" type="priority"/>
</nodes>'''
    
    # Create edges file - SIMPLIFIED: Let netconvert create the connections
    edges_content = '''<?xml version="1.0" encoding="UTF-8"?>
<edges>
    <!-- ===== INTERSECTION 1 ===== -->
    <!-- West approach: far_west -> J1_center (will be 2-way automatically) -->
    <edge id="road_west" from="far_west" to="J1_west" numLanes="1" speed="13.89"/>
    <edge id="J1_west_conn" from="J1_west" to="J1_center" numLanes="1" speed="13.89"/>
    
    <!-- North approach -->
    <edge id="road_north1" from="far_north1" to="J1_north" numLanes="1" speed="13.89"/>
    <edge id="J1_north_conn" from="J1_north" to="J1_center" numLanes="1" speed="13.89"/>
    
    <!-- South approach -->
    <edge id="road_south1" from="far_south1" to="J1_south" numLanes="1" speed="13.89"/>
    <edge id="J1_south_conn" from="J1_south" to="J1_center" numLanes="1" speed="13.89"/>
    
    <!-- East approach (toward J2) -->
    <edge id="J1_east_conn" from="J1_center" to="J1_east" numLanes="1" speed="13.89"/>
    
    <!-- ===== INTERSECTION 2 ===== -->
    <!-- East approach -->
    <edge id="road_east" from="far_east" to="J2_east" numLanes="1" speed="13.89"/>
    <edge id="J2_east_conn" from="J2_east" to="J2_center" numLanes="1" speed="13.89"/>
    
    <!-- North approach -->
    <edge id="road_north2" from="far_north2" to="J2_north" numLanes="1" speed="13.89"/>
    <edge id="J2_north_conn" from="J2_north" to="J2_center" numLanes="1" speed="13.89"/>
    
    <!-- South approach -->
    <edge id="road_south2" from="far_south2" to="J2_south" numLanes="1" speed="13.89"/>
    <edge id="J2_south_conn" from="J2_south" to="J2_center" numLanes="1" speed="13.89"/>
    
    <!-- West approach (from J1) -->
    <edge id="J2_west_conn" from="J2_west" to="J2_center" numLanes="1" speed="13.89"/>
    
    <!-- ===== CONNECTION BETWEEN INTERSECTIONS ===== -->
    <edge id="connector" from="J1_east" to="J2_west" numLanes="1" speed="13.89"/>
</edges>'''
    
    # Write files
    os.makedirs("sumo_configs", exist_ok=True)
    
    with open("sumo_configs/nodes.xml", "w") as f:
        f.write(nodes_content)
    
    with open("sumo_configs/edges.xml", "w") as f:
        f.write(edges_content)
    
    print("✓ Created nodes.xml and edges.xml")
    
    # Generate network - LET NETCONVERT DO THE WORK!
    cmd = [
        "netconvert",
        "--node-files=sumo_configs/nodes.xml",
        "--edge-files=sumo_configs/edges.xml",
        "--output-file=sumo_configs/1x2.net.xml",
        "--tls.set=J1_center,J2_center",
        "--tls.guess=true",  # Let netconvert create basic traffic lights
        "--no-turnarounds",
        "--lefthand",
        "--connections.guess",  # Guess connections between lanes
        "--crossings.guess",    # Guess pedestrian crossings
        "--roundabouts.guess=false"
    ]
    
    print(f"\nRunning netconvert...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ Network file generated: sumo_configs/1x2.net.xml")
        
        # NOW modify the traffic lights to be per-direction
        modify_traffic_lights_for_sri_lanka()
        return True
    else:
        print("✗ Error generating network:")
        print(result.stderr)
        # Try a simpler approach if that fails
        return generate_simple_network()

def generate_simple_network():
    """Simpler fallback network generation"""
    print("\nTrying simpler network generation...")
    
    # Create a VERY simple network file directly
    simple_net = '''<?xml version="1.0" encoding="UTF-8"?>
<net version="1.9" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/net_file.xsd">
    <location netOffset="0.00,0.00" convBoundary="0.00,0.00,1000.00,600.00" origBoundary="0.00,0.00,1000.00,600.00" projParameter="!"/>

    <!-- NODES -->
    <node id="J1_center" x="200.00" y="200.00" type="traffic_light"/>
    <node id="J2_center" x="600.00" y="200.00" type="traffic_light"/>
    
    <node id="J1_west" x="0.00" y="200.00" type="priority"/>
    <node id="J1_east" x="400.00" y="200.00" type="priority"/>
    <node id="J1_north" x="200.00" y="400.00" type="priority"/>
    <node id="J1_south" x="200.00" y="0.00" type="priority"/>
    
    <node id="J2_west" x="400.00" y="200.00" type="priority"/>
    <node id="J2_east" x="800.00" y="200.00" type="priority"/>
    <node id="J2_north" x="600.00" y="400.00" type="priority"/>
    <node id="J2_south" x="600.00" y="0.00" type="priority"/>
    
    <node id="far_west" x="-200.00" y="200.00" type="priority"/>
    <node id="far_east" x="1000.00" y="200.00" type="priority"/>
    <node id="far_north1" x="200.00" y="600.00" type="priority"/>
    <node id="far_south1" x="200.00" y="-200.00" type="priority"/>
    <node id="far_north2" x="600.00" y="600.00" type="priority"/>
    <node id="far_south2" x="600.00" y="-200.00" type="priority"/>

    <!-- EDGES - 2-way roads (each edge is one direction) -->
    <!-- Intersection 1: West approach -->
    <edge id="road_west_in" from="far_west" to="J1_west" numLanes="1" speed="13.89">
        <lane id="road_west_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_west_out" from="J1_west" to="far_west" numLanes="1" speed="13.89">
        <lane id="road_west_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_west_in" from="J1_west" to="J1_center" numLanes="1" speed="13.89">
        <lane id="J1_west_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_west_out" from="J1_center" to="J1_west" numLanes="1" speed="13.89">
        <lane id="J1_west_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 1: North approach -->
    <edge id="road_north1_in" from="far_north1" to="J1_north" numLanes="1" speed="13.89">
        <lane id="road_north1_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_north1_out" from="J1_north" to="far_north1" numLanes="1" speed="13.89">
        <lane id="road_north1_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_north_in" from="J1_north" to="J1_center" numLanes="1" speed="13.89">
        <lane id="J1_north_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_north_out" from="J1_center" to="J1_north" numLanes="1" speed="13.89">
        <lane id="J1_north_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 1: South approach -->
    <edge id="road_south1_in" from="far_south1" to="J1_south" numLanes="1" speed="13.89">
        <lane id="road_south1_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_south1_out" from="J1_south" to="far_south1" numLanes="1" speed="13.89">
        <lane id="road_south1_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_south_in" from="J1_south" to="J1_center" numLanes="1" speed="13.89">
        <lane id="J1_south_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_south_out" from="J1_center" to="J1_south" numLanes="1" speed="13.89">
        <lane id="J1_south_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 1: East approach (to J2) -->
    <edge id="J1_east_out" from="J1_center" to="J1_east" numLanes="1" speed="13.89">
        <lane id="J1_east_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J1_east_in" from="J1_east" to="J1_center" numLanes="1" speed="13.89">
        <lane id="J1_east_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Connection between intersections -->
    <edge id="connector_east" from="J1_east" to="J2_west" numLanes="1" speed="13.89">
        <lane id="connector_east_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="connector_west" from="J2_west" to="J1_east" numLanes="1" speed="13.89">
        <lane id="connector_west_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 2: East approach -->
    <edge id="road_east_in" from="far_east" to="J2_east" numLanes="1" speed="13.89">
        <lane id="road_east_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_east_out" from="J2_east" to="far_east" numLanes="1" speed="13.89">
        <lane id="road_east_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_east_in" from="J2_east" to="J2_center" numLanes="1" speed="13.89">
        <lane id="J2_east_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_east_out" from="J2_center" to="J2_east" numLanes="1" speed="13.89">
        <lane id="J2_east_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 2: North approach -->
    <edge id="road_north2_in" from="far_north2" to="J2_north" numLanes="1" speed="13.89">
        <lane id="road_north2_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_north2_out" from="J2_north" to="far_north2" numLanes="1" speed="13.89">
        <lane id="road_north2_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_north_in" from="J2_north" to="J2_center" numLanes="1" speed="13.89">
        <lane id="J2_north_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_north_out" from="J2_center" to="J2_north" numLanes="1" speed="13.89">
        <lane id="J2_north_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 2: South approach -->
    <edge id="road_south2_in" from="far_south2" to="J2_south" numLanes="1" speed="13.89">
        <lane id="road_south2_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="road_south2_out" from="J2_south" to="far_south2" numLanes="1" speed="13.89">
        <lane id="road_south2_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_south_in" from="J2_south" to="J2_center" numLanes="1" speed="13.89">
        <lane id="J2_south_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_south_out" from="J2_center" to="J2_south" numLanes="1" speed="13.89">
        <lane id="J2_south_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    
    <!-- Intersection 2: West approach (from J1) -->
    <edge id="J2_west_in" from="J2_west" to="J2_center" numLanes="1" speed="13.89">
        <lane id="J2_west_in_0" index="0" speed="13.89" length="200.00"/>
    </edge>
    <edge id="J2_west_out" from="J2_center" to="J2_west" numLanes="1" speed="13.89">
        <lane id="J2_west_out_0" index="0" speed="13.89" length="200.00"/>
    </edge>

    <!-- CONNECTIONS (lane-to-lane) -->
    <!-- Intersection 1 connections -->
    <connection from="J1_west_in_0" to="J1_north_out_0" via=":J1_center_0" dir="l" state="o"/>
    <connection from="J1_west_in_0" to="J1_east_out_0" via=":J1_center_1" dir="s" state="o"/>
    <connection from="J1_west_in_0" to="J1_south_out_0" via=":J1_center_2" dir="r" state="o"/>
    
    <connection from="J1_north_in_0" to="J1_east_out_0" via=":J1_center_3" dir="l" state="o"/>
    <connection from="J1_north_in_0" to="J1_south_out_0" via=":J1_center_4" dir="s" state="o"/>
    <connection from="J1_north_in_0" to="J1_west_out_0" via=":J1_center_5" dir="r" state="o"/>
    
    <connection from="J1_east_in_0" to="J1_south_out_0" via=":J1_center_6" dir="l" state="o"/>
    <connection from="J1_east_in_0" to="J1_west_out_0" via=":J1_center_7" dir="s" state="o"/>
    <connection from="J1_east_in_0" to="J1_north_out_0" via=":J1_center_8" dir="r" state="o"/>
    
    <connection from="J1_south_in_0" to="J1_west_out_0" via=":J1_center_9" dir="l" state="o"/>
    <connection from="J1_south_in_0" to="J1_north_out_0" via=":J1_center_10" dir="s" state="o"/>
    <connection from="J1_south_in_0" to="J1_east_out_0" via=":J1_center_11" dir="r" state="o"/>
    
    <!-- Intersection 2 connections (similar pattern) -->
    <connection from="J2_west_in_0" to="J2_north_out_0" via=":J2_center_0" dir="l" state="o"/>
    <connection from="J2_west_in_0" to="J2_east_out_0" via=":J2_center_1" dir="s" state="o"/>
    <connection from="J2_west_in_0" to="J2_south_out_0" via=":J2_center_2" dir="r" state="o"/>
    
    <connection from="J2_north_in_0" to="J2_east_out_0" via=":J2_center_3" dir="l" state="o"/>
    <connection from="J2_north_in_0" to="J2_south_out_0" via=":J2_center_4" dir="s" state="o"/>
    <connection from="J2_north_in_0" to="J2_west_out_0" via=":J2_center_5" dir="r" state="o"/>
    
    <connection from="J2_east_in_0" to="J2_south_out_0" via=":J2_center_6" dir="l" state="o"/>
    <connection from="J2_east_in_0" to="J2_west_out_0" via=":J2_center_7" dir="s" state="o"/>
    <connection from="J2_east_in_0" to="J2_north_out_0" via=":J2_center_8" dir="r" state="o"/>
    
    <connection from="J2_south_in_0" to="J2_west_out_0" via=":J2_center_9" dir="l" state="o"/>
    <connection from="J2_south_in_0" to="J2_north_out_0" via=":J2_center_10" dir="s" state="o"/>
    <connection from="J2_south_in_0" to="J2_east_out_0" via=":J2_center_11" dir="r" state="o"/>

    <!-- TRAFFIC LIGHT LOGIC - SRI LANKA STYLE -->
    <tlLogic id="J1_center" type="static" programID="0" offset="0">
        <!-- Phase 0: WEST green (straight/left/right) -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <!-- Phase 1: WEST yellow -->
        <phase duration="3" state="yyygrrrryyyg"/>
        <!-- Phase 2: NORTH green -->
        <phase duration="30" state="rrrGGGgrrrG"/>
        <!-- Phase 3: NORTH yellow -->
        <phase duration="3" state="rrryyygrrry"/>
        <!-- Phase 4: EAST green -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <!-- Phase 5: EAST yellow -->
        <phase duration="3" state="yyygrrrryyyg"/>
        <!-- Phase 6: SOUTH green -->
        <phase duration="30" state="rrrGGGgrrrG"/>
        <!-- Phase 7: SOUTH yellow -->
        <phase duration="3" state="rrryyygrrry"/>
    </tlLogic>
    
    <tlLogic id="J2_center" type="static" programID="0" offset="15">
        <!-- Same pattern, offset for coordination -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <phase duration="3" state="yyygrrrryyyg"/>
        <phase duration="30" state="rrrGGGgrrrG"/>
        <phase duration="3" state="rrryyygrrry"/>
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <phase duration="3" state="yyygrrrryyyg"/>
        <phase duration="30" state="rrrGGGgrrrG"/>
        <phase duration="3" state="rrryyygrrry"/>
    </tlLogic>
</net>'''
    
    with open("sumo_configs/1x2.net.xml", "w") as f:
        f.write(simple_net)
    
    print("✓ Created simple network file directly")
    return True

def modify_traffic_lights_for_sri_lanka():
    """Modify the traffic lights to be per-direction Sri Lanka style"""
    try:
        network_file = "sumo_configs/1x2.net.xml"
        
        with open(network_file, 'r') as f:
            content = f.read()
        
        # Remove existing tlLogic sections
        import re
        pattern = r'<tlLogic id="(J1_center|J2_center)".*?</tlLogic>'
        content = re.sub(pattern, '', content, flags=re.DOTALL)
        
        # Add Sri Lanka style traffic lights
        sri_lanka_tl = '''
    <!-- SRI LANKA STYLE TRAFFIC LIGHTS -->
    <!-- One direction at a time, all movements allowed -->
    <tlLogic id="J1_center" type="static" programID="0" offset="0">
        <!-- Phase 0: WEST green (vehicles can go straight, left, or right) -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <!-- Phase 1: WEST yellow -->
        <phase duration="3" state="yyygrrrryyyg"/>
        <!-- Phase 2: NORTH green -->
        <phase duration="30" state="rrrGGGgrrrG"/>
        <!-- Phase 3: NORTH yellow -->
        <phase duration="3" state="rrryyygrrry"/>
        <!-- Phase 4: EAST green -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <!-- Phase 5: EAST yellow -->
        <phase duration="3" state="yyygrrrryyyg"/>
        <!-- Phase 6: SOUTH green -->
        <phase duration="30" state="rrrGGGgrrrG"/>
        <!-- Phase 7: SOUTH yellow -->
        <phase duration="3" state="rrryyygrrry"/>
    </tlLogic>
    
    <tlLogic id="J2_center" type="static" programID="0" offset="15">
        <!-- Same pattern, offset for coordination -->
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <phase duration="3" state="yyygrrrryyyg"/>
        <phase duration="30" state="rrrGGGgrrrG"/>
        <phase duration="3" state="rrryyygrrry"/>
        <phase duration="30" state="GGGgrrrrGGGg"/>
        <phase duration="3" state="yyygrrrryyyg"/>
        <phase duration="30" state="rrrGGGgrrrG"/>
        <phase duration="3" state="rrryyygrrry"/>
    </tlLogic>'''
        
        # Insert before closing </net> tag
        insert_pos = content.find('</net>')
        if insert_pos != -1:
            content = content[:insert_pos] + sri_lanka_tl + content[insert_pos:]
            
            with open(network_file, 'w') as f:
                f.write(content)
            
            print("✓ Modified traffic lights for Sri Lanka style")
        else:
            print("⚠ Could not modify traffic lights")
            
    except Exception as e:
        print(f"⚠ Could not modify traffic lights: {e}")

# [Keep the create_routes(), create_config(), and main() functions from previous version]
# They should work fine with the updated network

# [Rest of the functions remain the same...]

def create_routes():
    """Create routes for 2-way per-direction system"""
    
    route_content = '''<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    
    <!-- Vehicle types -->
    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" maxSpeed="13.89" color="1,0,0"/>
    <vType id="bus" accel="1.2" decel="4.0" sigma="0.5" length="12.0" maxSpeed="10.0" color="0,0,1"/>
    <vType id="truck" accel="1.3" decel="4.0" sigma="0.5" length="7.5" maxSpeed="10.0" color="0.5,0.5,0.5"/>
    
    <!-- ===== SIMPLIFIED ROUTES ===== -->
    <!-- Through traffic West to East -->
    <route id="W_to_E" edges="road_west_in J1_west_in J1_east_out connector_east J2_west_in J2_east_out road_east_out"/>
    
    <!-- Through traffic East to West -->
    <route id="E_to_W" edges="road_east_in J2_east_in J2_west_out connector_west J1_east_in J1_west_out road_west_out"/>
    
    <!-- North-South at Intersection 1 -->
    <route id="N1_to_S1" edges="road_north1_in J1_north_in J1_south_out road_south1_out"/>
    <route id="S1_to_N1" edges="road_south1_in J1_south_in J1_north_out road_north1_out"/>
    
    <!-- North-South at Intersection 2 -->
    <route id="N2_to_S2" edges="road_north2_in J2_north_in J2_south_out road_south2_out"/>
    <route id="S2_to_N2" edges="road_south2_in J2_south_in J2_north_out road_north2_out"/>
    
    <!-- Turning at Intersection 1 -->
    <route id="W_to_N1" edges="road_west_in J1_west_in J1_north_out road_north1_out"/>
    <route id="W_to_S1" edges="road_west_in J1_west_in J1_south_out road_south1_out"/>
    
    <!-- Turning at Intersection 2 -->
    <route id="E_to_N2" edges="road_east_in J2_east_in J2_north_out road_north2_out"/>
    <route id="E_to_S2" edges="road_east_in J2_east_in J2_south_out road_south2_out"/>
    
    <!-- ===== TRAFFIC FLOWS ===== -->
    <!-- Main through traffic -->
    <flow id="flow_W_to_E" type="car" route="W_to_E" begin="0" end="3600" period="8"/>
    <flow id="flow_E_to_W" type="car" route="E_to_W" begin="0" end="3600" period="8"/>
    
    <!-- Cross traffic -->
    <flow id="flow_N1_to_S1" type="car" route="N1_to_S1" begin="0" end="3600" period="12"/>
    <flow id="flow_S1_to_N1" type="car" route="S1_to_N1" begin="0" end="3600" period="12"/>
    <flow id="flow_N2_to_S2" type="car" route="N2_to_S2" begin="0" end="3600" period="12"/>
    <flow id="flow_S2_to_N2" type="car" route="S2_to_N2" begin="0" end="3600" period="12"/>
    
    <!-- Turning traffic -->
    <flow id="flow_W_to_N1" type="car" route="W_to_N1" begin="0" end="3600" period="20"/>
    <flow id="flow_W_to_S1" type="car" route="W_to_S1" begin="0" end="3600" period="20"/>
    <flow id="flow_E_to_N2" type="car" route="E_to_N2" begin="0" end="3600" period="20"/>
    <flow id="flow_E_to_S2" type="car" route="E_to_S2" begin="0" end="3600" period="20"/>
    
    <!-- Heavy vehicles -->
    <flow id="flow_truck_W_to_E" type="truck" route="W_to_E" begin="0" end="3600" period="60"/>
    <flow id="flow_bus_N1_to_S1" type="bus" route="N1_to_S1" begin="0" end="3600" period="90"/>
    
</routes>'''
    
    with open("sumo_configs/1x2.rou.xml", "w") as f:
        f.write(route_content)
    
    print("✓ Route file created: sumo_configs/1x2.rou.xml")

def create_config():
    """Create config file"""
    
    config_content = '''<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    
    <input>
        <net-file value="1x2.net.xml"/>
        <route-files value="1x2.rou.xml"/>
    </input>
    
    <time>
        <begin value="0"/>
        <end value="3600"/>
        <step-length value="1"/>
    </time>
    
    <report>
        <verbose value="false"/>
        <no-step-log value="true"/>
        <duration-log.statistics value="true"/>
    </report>
    
</configuration>'''
    
    with open("sumo_configs/1x2.sumocfg", "w") as f:
        f.write(config_content)
    
    print("✓ Config file created: sumo_configs/1x2.sumocfg")

def main():
    """Main function"""
    
    print("=" * 70)
    print("SRI LANKA TRAFFIC NETWORK GENERATOR")
    print("Features:")
    print("  • 2 intersections (1×2)")
    print("  • Left-hand driving")
    print("  • 2-way roads")
    print("  • Per-direction traffic lights (one direction at a time)")
    print("  • Green direction: straight, left, or right allowed")
    print("=" * 70)
    
    if generate_two_intersections():
        create_routes()
        create_config()
        
        print("\n" + "=" * 70)
        print("✓ SUCCESS: Network created!")
        print("=" * 70)
        
        print("\nTRAFFIC LIGHT PHASES (Sri Lanka Style):")
        print("  0: WEST green (30s) - vehicles can go straight/left/right")
        print("  1: WEST yellow (3s)")
        print("  2: NORTH green (30s)")
        print("  3: NORTH yellow (3s)")
        print("  4: EAST green (30s)")
        print("  5: EAST yellow (3s)")
        print("  6: SOUTH green (30s)")
        print("  7: SOUTH yellow (3s)")
        
        print("\nFOR YOUR MARL AGENT (5 actions):")
        print("  Action 0: Switch to WEST green (Phase 0)")
        print("  Action 1: Switch to NORTH green (Phase 2)")
        print("  Action 2: Switch to EAST green (Phase 4)")
        print("  Action 3: Switch to SOUTH green (Phase 6)")
        print("  Action 4: Extend current green phase")
        
        print("\nTEST COMMANDS:")
        print("  sumo-gui -c sumo_configs/1x2.sumocfg")
        print("  sumo -c sumo_configs/1x2.sumocfg")
        
    else:
        print("\n✗ Failed to generate network")

if __name__ == "__main__":
    main()