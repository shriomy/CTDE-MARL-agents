"""
Add test data with ISO 8601 timestamp format to MongoDB.
Timestamp format: 2026-03-04T07:26:18.513+00:00
"""
import pymongo
from datetime import datetime, timezone, timedelta
import time

# MongoDB connection
client = pymongo.MongoClient("mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0")
db = client["EmergencyDetection"]
collection = db["SUMOinjections"]

print("Clearing old test data...")
collection.delete_many({})  # Clear all for clean test

print("Adding test data with ISO 8601 timestamps...")

# Function to create ISO 8601 timestamp
def get_iso_timestamp(offset_seconds=0):
    """Get current time in ISO 8601 format with timezone"""
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

# Test Emergency Vehicle
emergency_record = {
    "timestamp": get_iso_timestamp(0),  # ISO format: 2026-03-04T07:26:18.513+00:00
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "ambulance",
        "entryPoint": "-E4"  # Coming from north
    }
}
result = collection.insert_one(emergency_record)
print(f"Added emergency vehicle: {result.inserted_id}")
print(f"  Timestamp: {emergency_record['timestamp']}")

# Test Pedestrians
pedestrian_record = {
    "timestamp": get_iso_timestamp(2),  # 2 seconds later
    "type": "pedestrian",
    "data": {
        "pedestrians": [
            {"type": "elderly", "position": "south_side", "count": 2},  
            {"type": "student", "position": "north_side", "count": 5},      
            {"type": "adult", "position": "south_side", "count": 3},        
            {"type": "mobility_aid", "position": "north_side", "count": 4},   
        ]
    }
}
result = collection.insert_one(pedestrian_record)
print(f"Added pedestrians: {result.inserted_id}")
print(f"  Timestamp: {pedestrian_record['timestamp']}")

# Test Normal Vehicles
normal_record = {
    "timestamp": get_iso_timestamp(4),  # 4 seconds later
    "type": "normal_vehicle",
    "data": {
        "entryPoint": "-E0",  # Coming from west
        "vehicles": [
            {"type": "truck", "count": 1},
            {"type": "car", "count": 2},
            {"type": "lorry", "count": 5},
            {"type": "bus", "count": 1},
            {"type": "auto", "count": 3},
            {"type": "bike", "count": 4},
        ]
    }
}
result = collection.insert_one(normal_record)
print(f"Added normal vehicles: {result.inserted_id}")
print(f"  Timestamp: {normal_record['timestamp']}")

# Add one more emergency vehicle (police) for variety
police_record = {
    "timestamp": get_iso_timestamp(6),
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "police",
        "entryPoint": "-E5"  # Coming from east
    }
}
result = collection.insert_one(police_record)
print(f"Added police vehicle: {result.inserted_id}")
print(f"  Timestamp: {police_record['timestamp']}")

fireTruck_record = {
    "timestamp": get_iso_timestamp(6),
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "firetruck",
        "entryPoint": "-E5"  # Coming from east
    }
}
result = collection.insert_one(fireTruck_record)
print(f"Added firetruck vehicle: {result.inserted_id}")
print(f"  Timestamp: {fireTruck_record['timestamp']}")

print("\n" + "="*60)
print("TEST DATA ADDED SUCCESSFULLY!")
print("="*60)
print("\nRecords in database:")
for doc in collection.find().sort("timestamp", pymongo.ASCENDING):
    print(f"  - Type: {doc['type']}")
    print(f"    Timestamp: {doc['timestamp']}")
    if doc['type'] == 'emergency_vehicle':
        print(f"    Vehicle: {doc['data']['vehicle_type']} at {doc['data']['entryPoint']}")
    elif doc['type'] == 'normal_vehicle':
        vehicles = doc['data'].get('vehicles', [])
        summary = ", ".join(f"{v.get('type')}={v.get('count')}" for v in vehicles)
        print(f"    Vehicles: [{summary}] at {doc['data']['entryPoint']}")
    elif doc['type'] == 'pedestrian':
        total = sum(p['count'] for p in doc['data']['pedestrians'])
        print(f"    Total pedestrians: {total}")

print("\n" + "="*60)
print("Now run the injector with:")
print("python -m data_injection.run_injector --sumo-config sumo_configs/3junctions.sumocfg --gui --interval 1.0")
print("="*60)

# Close connection
client.close()