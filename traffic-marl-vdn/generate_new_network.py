import subprocess
import os

# Create a simple .nod.xml file
nodes_content = """<?xml version="1.0" encoding="UTF-8"?>
<nodes>
    <!-- Intersection 1 -->
    <node id="J1" x="100" y="100" type="traffic_light"/>
    
    <!-- Intersection 2 -->
    <node id="J2" x="400" y="100" type="traffic_light"/>
    
    <!-- Terminal nodes -->
    <node id="west1" x="0" y="100" type="priority"/>
    <node id="east1" x="200" y="100" type="priority"/>
    <node id="north1" x="100" y="200" type="priority"/>
    <node id="south1" x="100" y="0" type="priority"/>
    
    <node id="west2" x="300" y="100" type="priority"/>
    <node id="east2" x="500" y="100" type="priority"/>
    <node id="north2" x="400" y="200" type="priority"/>
    <node id="south2" x="400" y="0" type="priority"/>
</nodes>"""

# Create a simple .edg.xml file
edges_content = """<?xml version="1.0" encoding="UTF-8"?>
<edges>
    <!-- Intersection 1 -->
    <edge id="J1_west_in" from="west1" to="J1" numLanes="2" speed="50"/>
    <edge id="J1_west_out" from="J1" to="west1" numLanes="2" speed="50"/>
    
    <edge id="J1_east_in" from="east1" to="J1" numLanes="2" speed="50"/>
    <edge id="J1_east_out" from="J1" to="east1" numLanes="2" speed="50"/>
    
    <edge id="J1_north_in" from="north1" to="J1" numLanes="2" speed="50"/>
    <edge id="J1_north_out" from="J1" to="north1" numLanes="2" speed="50"/>
    
    <edge id="J1_south_in" from="south1" to="J1" numLanes="2" speed="50"/>
    <edge id="J1_south_out" from="J1" to="south1" numLanes="2" speed="50"/>
    
    <!-- Intersection 2 -->
    <edge id="J2_west_in" from="west2" to="J2" numLanes="2" speed="50"/>
    <edge id="J2_west_out" from="J2" to="west2" numLanes="2" speed="50"/>
    
    <edge id="J2_east_in" from="east2" to="J2" numLanes="2" speed="50"/>
    <edge id="J2_east_out" from="J2" to="east2" numLanes="2" speed="50"/>
    
    <edge id="J2_north_in" from="north2" to="J2" numLanes="2" speed="50"/>
    <edge id="J2_north_out" from="J2" to="north2" numLanes="2" speed="50"/>
    
    <edge id="J2_south_in" from="south2" to="J2" numLanes="2" speed="50"/>
    <edge id="J2_south_out" from="J2" to="south2" numLanes="2" speed="50"/>
    
    <!-- Connecting road -->
    <edge id="connector1" from="east1" to="west2" numLanes="2" speed="50"/>
    <edge id="connector2" from="west2" to="east1" numLanes="2" speed="50"/>
</edges>"""

# Save files
os.makedirs("sumo_configs", exist_ok=True)
with open("sumo_configs/nodes.xml", "w") as f:
    f.write(nodes_content)
with open("sumo_configs/edges.xml", "w") as f:
    f.write(edges_content)

# Use netconvert to generate the network
print("Generating network with netconvert...")
cmd = [
    "netconvert",
    "--node-files", "sumo_configs/nodes.xml",
    "--edge-files", "sumo_configs/edges.xml",
    "--output-file", "sumo_configs/1x2_simple.net.xml",
    "--lefthand",
    "--tls.set", "J1,J2",
    "--tls.guess", "true",
    "--tls.join", "true"
]

try:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("Network generated successfully!")
        print("Output:", result.stdout)
    else:
        print("Error generating network:")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
except FileNotFoundError:
    print("netconvert not found. Make sure SUMO is installed and in PATH.")