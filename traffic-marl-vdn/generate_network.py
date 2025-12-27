import os
import subprocess
import sys

def generate_two_intersections():
    """Generate two connected 4-way intersections"""
    
    print("Creating two connected 4-way intersections...")
    
    # Create nodes file - Two intersections with 4 approaches each
    nodes_content = '''<?xml version="1.0" encoding="UTF-8"?>
<nodes>
    <!-- INTERSECTION 1 (Left) -->
    <node id="J1_center" x="200" y="200" type="traffic_light"/>
    <node id="J1_north" x="200" y="400" type="priority"/>
    <node id="J1_east" x="300" y="200" type="priority"/>  <!-- Connects to J2 -->
    <node id="J1_south" x="200" y="0" type="priority"/>
    <node id="J1_west" x="0" y="200" type="priority"/>
    
    <!-- INTERSECTION 2 (Right) -->
    <node id="J2_center" x="500" y="200" type="traffic_light"/>
    <node id="J2_north" x="500" y="400" type="priority"/>
    <node id="J2_east" x="700" y="200" type="priority"/>
    <node id="J2_south" x="500" y="0" type="priority"/>
    <node id="J2_west" x="300" y="200" type="priority"/>  <!-- Connects to J1 -->
    
    <!-- Edge nodes for longer roads -->
    <node id="far_west" x="-200" y="200" type="priority"/>
    <node id="far_east" x="900" y="200" type="priority"/>
    <node id="far_north1" x="200" y="600" type="priority"/>
    <node id="far_south1" x="200" y="-200" type="priority"/>
    <node id="far_north2" x="500" y="600" type="priority"/>
    <node id="far_south2" x="500" y="-200" type="priority"/>
</nodes>'''
    
    # Create edges file
    edges_content = '''<?xml version="1.0" encoding="UTF-8"?>
<edges>
    <!-- ===== INTERSECTION 1 ===== -->
    <!-- Long approach roads to J1 -->
    <edge id="J1_west_approach" from="far_west" to="J1_west" numLanes="2" speed="13.89"/>
    <edge id="J1_west_in" from="J1_west" to="J1_center" numLanes="2" speed="13.89"/>
    <edge id="J1_west_out" from="J1_center" to="J1_west" numLanes="2" speed="13.89"/>
    <edge id="J1_west_exit" from="J1_west" to="far_west" numLanes="2" speed="13.89"/>
    
    <edge id="J1_east_approach" from="J1_east" to="J2_west" numLanes="2" speed="13.89"/> <!-- Connector -->
    <edge id="J1_east_in" from="J2_west" to="J1_center" numLanes="2" speed="13.89"/>
    <edge id="J1_east_out" from="J1_center" to="J2_west" numLanes="2" speed="13.89"/>
    <edge id="J1_east_exit" from="J2_west" to="J1_east" numLanes="2" speed="13.89"/>
    
    <edge id="J1_north_approach" from="far_north1" to="J1_north" numLanes="2" speed="13.89"/>
    <edge id="J1_north_in" from="J1_north" to="J1_center" numLanes="2" speed="13.89"/>
    <edge id="J1_north_out" from="J1_center" to="J1_north" numLanes="2" speed="13.89"/>
    <edge id="J1_north_exit" from="J1_north" to="far_north1" numLanes="2" speed="13.89"/>
    
    <edge id="J1_south_approach" from="far_south1" to="J1_south" numLanes="2" speed="13.89"/>
    <edge id="J1_south_in" from="J1_south" to="J1_center" numLanes="2" speed="13.89"/>
    <edge id="J1_south_out" from="J1_center" to="J1_south" numLanes="2" speed="13.89"/>
    <edge id="J1_south_exit" from="J1_south" to="far_south1" numLanes="2" speed="13.89"/>
    
    <!-- ===== INTERSECTION 2 ===== -->
    <edge id="J2_west_approach" from="J2_west" to="J1_east" numLanes="2" speed="13.89"/> <!-- Connector -->
    <edge id="J2_west_in" from="J1_east" to="J2_center" numLanes="2" speed="13.89"/>
    <edge id="J2_west_out" from="J2_center" to="J1_east" numLanes="2" speed="13.89"/>
    <edge id="J2_west_exit" from="J1_east" to="J2_west" numLanes="2" speed="13.89"/>
    
    <edge id="J2_east_approach" from="far_east" to="J2_east" numLanes="2" speed="13.89"/>
    <edge id="J2_east_in" from="J2_east" to="J2_center" numLanes="2" speed="13.89"/>
    <edge id="J2_east_out" from="J2_center" to="J2_east" numLanes="2" speed="13.89"/>
    <edge id="J2_east_exit" from="J2_east" to="far_east" numLanes="2" speed="13.89"/>
    
    <edge id="J2_north_approach" from="far_north2" to="J2_north" numLanes="2" speed="13.89"/>
    <edge id="J2_north_in" from="J2_north" to="J2_center" numLanes="2" speed="13.89"/>
    <edge id="J2_north_out" from="J2_center" to="J2_north" numLanes="2" speed="13.89"/>
    <edge id="J2_north_exit" from="J2_north" to="far_north2" numLanes="2" speed="13.89"/>
    
    <edge id="J2_south_approach" from="far_south2" to="J2_south" numLanes="2" speed="13.89"/>
    <edge id="J2_south_in" from="J2_south" to="J2_center" numLanes="2" speed="13.89"/>
    <edge id="J2_south_out" from="J2_center" to="J2_south" numLanes="2" speed="13.89"/>
    <edge id="J2_south_exit" from="J2_south" to="far_south2" numLanes="2" speed="13.89"/>
</edges>'''
    
    # Write files
    os.makedirs("sumo_configs", exist_ok=True)
    
    with open("sumo_configs/nodes.xml", "w") as f:
        f.write(nodes_content)
    
    with open("sumo_configs/edges.xml", "w") as f:
        f.write(edges_content)
    
    print("✓ Created nodes.xml and edges.xml")
    
    # Generate network using netconvert
    cmd = [
        "netconvert",
        "--node-files=sumo_configs/nodes.xml",
        "--edge-files=sumo_configs/edges.xml",
        "--output-file=sumo_configs/1x2.net.xml",
        "--tls.set=J1_center,J2_center",
        "--tls.guess=true",
        "--no-turnarounds",
        "--junctions.join=true",
        "--lefthand"
    ]
    
    print(f"\nRunning netconvert...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✓ Network file generated: sumo_configs/1x2.net.xml")
        return True
    else:
        print("✗ Error generating network:")
        print(result.stderr)
        return False

def create_complex_routes():
    """Create routes for all possible movements"""
    
    route_content = '''<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    
    <!-- Vehicle types -->
    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5.0" maxSpeed="50.0" color="1,0,0"/>
    <vType id="bus" accel="1.2" decel="4.0" sigma="0.5" length="12.0" maxSpeed="30.0" color="0,0,1"/>
    <vType id="truck" accel="1.3" decel="4.0" sigma="0.5" length="7.5" maxSpeed="40.0" color="0.5,0.5,0.5"/>
    
    <!-- ===== ROUTES THROUGH BOTH INTERSECTIONS ===== -->
    <!-- West to East through both intersections -->
    <route id="W_to_E" edges="J1_west_approach J1_west_in J1_west_out J1_east_exit J2_west_approach J2_west_in J2_west_out J2_east_exit"/>
    
    <!-- East to West through both intersections -->
    <route id="E_to_W" edges="J2_east_approach J2_east_in J2_east_out J2_west_exit J1_east_approach J1_east_in J1_east_out J1_west_exit"/>
    
    <!-- North to South at Intersection 1 -->
    <route id="N1_to_S1" edges="J1_north_approach J1_north_in J1_north_out J1_south_exit"/>
    
    <!-- South to North at Intersection 1 -->
    <route id="S1_to_N1" edges="J1_south_approach J1_south_in J1_south_out J1_north_exit"/>
    
    <!-- North to South at Intersection 2 -->
    <route id="N2_to_S2" edges="J2_north_approach J2_north_in J2_north_out J2_south_exit"/>
    
    <!-- South to North at Intersection 2 -->
    <route id="S2_to_N2" edges="J2_south_approach J2_south_in J2_south_out J2_north_exit"/>
    
    <!-- Turning routes at Intersection 1 -->
    <route id="W_to_N1" edges="J1_west_approach J1_west_in J1_west_out J1_north_exit"/>
    <route id="W_to_S1" edges="J1_west_approach J1_west_in J1_west_out J1_south_exit"/>
    
    <!-- Turning routes at Intersection 2 -->
    <route id="E_to_N2" edges="J2_east_approach J2_east_in J2_east_out J2_north_exit"/>
    <route id="E_to_S2" edges="J2_east_approach J2_east_in J2_east_out J2_south_exit"/>
    
    <!-- ===== TRAFFIC FLOWS ===== -->
    <!-- Main through traffic (West to East) -->
    <flow id="flow_W_to_E" type="car" route="W_to_E" begin="0" end="3600" period="8"/>
    
    <!-- Main through traffic (East to West) -->
    <flow id="flow_E_to_W" type="car" route="E_to_W" begin="0" end="3600" period="10"/>
    
    <!-- North-South traffic at Intersection 1 -->
    <flow id="flow_N1_to_S1" type="car" route="N1_to_S1" begin="0" end="3600" period="12"/>
    <flow id="flow_S1_to_N1" type="car" route="S1_to_N1" begin="0" end="3600" period="15"/>
    
    <!-- North-South traffic at Intersection 2 -->
    <flow id="flow_N2_to_S2" type="car" route="N2_to_S2" begin="0" end="3600" period="12"/>
    <flow id="flow_S2_to_N2" type="car" route="S2_to_N2" begin="0" end="3600" period="15"/>
    
    <!-- Turning traffic -->
    <flow id="flow_W_to_N1" type="car" route="W_to_N1" begin="0" end="3600" period="20"/>
    <flow id="flow_W_to_S1" type="car" route="W_to_S1" begin="0" end="3600" period="25"/>
    <flow id="flow_E_to_N2" type="car" route="E_to_N2" begin="0" end="3600" period="20"/>
    <flow id="flow_E_to_S2" type="car" route="E_to_S2" begin="0" end="3600" period="25"/>
    
    <!-- Heavy vehicles -->
    <flow id="flow_truck_W_to_E" type="truck" route="W_to_E" begin="0" end="3600" period="60"/>
    <flow id="flow_bus_N1_to_S1" type="bus" route="N1_to_S1" begin="0" end="3600" period="120"/>
    
</routes>'''
    
    with open("sumo_configs/1x2.rou.xml", "w") as f:
        f.write(route_content)
    
    print("✓ Route file created: sumo_configs/1x2.rou.xml")

def create_enhanced_config():
    """Create enhanced config file"""
    
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
        <verbose value="true"/>
        <no-step-log value="true"/>
        <duration-log.statistics value="true"/>
    </report>
    
    <gui_only>
        <gui-settings-file value="gui-settings.xml"/>
        <delay value="50"/>
    </gui_only>
    
</configuration>'''
    
    with open("sumo_configs/1x2.sumocfg", "w") as f:
        f.write(config_content)
    
    print("✓ Config file created: sumo_configs/1x2.sumocfg")

def create_gui_settings():
    """Create GUI settings for better visualization"""
    
    gui_settings = '''<?xml version="1.0" encoding="UTF-8"?>
<viewsettings>
    <scheme name="real world"/>
    <viewport zoom="100" x="350" y="200"/>
    <delay value="50"/>
    <show-route-ids value="true"/>
    <show-vehicle-ids value="true"/>
    <lane-show-borders value="true"/>
    <show-link-rule value="true"/>
    <show-link-tls value="true"/>
</viewsettings>'''
    
    with open("sumo_configs/gui-settings.xml", "w") as f:
        f.write(gui_settings)
    
    print("✓ GUI settings created: sumo_configs/gui-settings.xml")

def main():
    """Main function"""
    
    print("=" * 70)
    print("TWO 4-WAY INTERSECTION NETWORK GENERATOR")
    print("=" * 70)
    print("\nCreating: Two connected 4-way intersections")
    print("          Each with N, E, W, S approaches")
    print("          Traffic lights at both intersections")
    print("          Multiple vehicle routes")
    print("=" * 70)
    
    # Generate network
    if generate_two_intersections():
        create_complex_routes()
        create_enhanced_config()
        create_gui_settings()
        
        print("\n" + "=" * 70)
        print("✓ SUCCESS: Realistic 2-intersection network created!")
        print("=" * 70)
        
        print("\nNETWORK FEATURES:")
        print("1. Two 4-way intersections (J1_center and J2_center)")
        print("2. Connected by a road between them")
        print("3. Each has: North, East, South, West approaches")
        print("4. 2 lanes per direction")
        print("5. Multiple vehicle types and routes")
        
        print("\nTRAFFIC LIGHT IDs (for your RL agents):")
        print("  - J1_center (Left intersection)")
        print("  - J2_center (Right intersection)")
        
        print("\nROAD APPROACHES for communication:")
        print("  Intersection 1: J1_west_in, J1_east_in, J1_north_in, J1_south_in")
        print("  Intersection 2: J2_west_in, J2_east_in, J2_north_in, J2_south_in")
        
        print("\nTEST COMMANDS:")
        print("1. View network: sumo-gui -c sumo_configs/1x2.sumocfg")
        print("2. Test without GUI: sumo -c sumo_configs/1x2.sumocfg")
        print("3. Check traffic lights: grep 'tlLogic' sumo_configs/1x2.net.xml")
        
        print("\nFor your MARL system:")
        print("- Agent 1 controls: J1_center")
        print("- Agent 2 controls: J2_center")
        print("- They communicate about: outgoing vehicle counts")
        print("- Each monitors: queue lengths on 4 approaches")
        
    else:
        print("\n✗ Failed to generate network")
        print("Try running: netconvert --help")
        print("Make sure SUMO is in PATH")

if __name__ == "__main__":
    main()