"""
Add test data with BSON Date timestamps to MongoDB.
MongoDB stores these as Date values (not quoted string literals).
"""
import pymongo
from datetime import datetime, timezone, timedelta

# MongoDB connection
client = pymongo.MongoClient("mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0")
db = client["EmergencyDetection"]
collection = db["SUMOinjections"]

# print("Clearing old test data...")
# collection.delete_many({})  # Clear all for clean test

print("Adding test data with BSON Date timestamps...")

# Function to create BSON datetime value
def get_bson_timestamp(offset_seconds=0):
    """Get timezone-aware UTC datetime for MongoDB Date storage."""
    return datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)


def to_iso_display(dt):
    """Render datetime as ISO string for console logs only."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"

# Test Emergency Vehicle
# emergency_record = {
#     "timestamp": get_bson_timestamp(0),  # Stored as MongoDB Date (BSON datetime)
#     "type": "emergency_vehicle",
#     "data": {
#         "vehicle_type": "ambulance",
#         "entryPoint": "-E4"  # E0, -E2, -E8, -E4, -E5
#     }
# }
# result = collection.insert_one(emergency_record)
# print(f"Added emergency vehicle: {result.inserted_id}")
# print(f"  Timestamp: {to_iso_display(emergency_record['timestamp'])}")

# Test Pedestrians
pedestrian_record = {
    "timestamp": get_bson_timestamp(2),  # 2 seconds later
    "type": "pedestrian",
    "data": {
        "pedestrians": [
            {"type": "elderly", "position": "south_side", "count": 9},  
            {"type": "student", "position": "north_side", "count": 5},      
            {"type": "adult", "position": "south_side", "count": 3},        
            {"type": "mobility_aid", "position": "north_side", "count": 9},   
        ]
    }
}
result = collection.insert_one(pedestrian_record)
print(f"Added pedestrians: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(pedestrian_record['timestamp'])}")

# Test Normal Vehicles
normal_record = {
    "timestamp": get_bson_timestamp(4),  # 4 seconds later
    "type": "normal_vehicle",
    "data": {
        "entryPoint": "-E4",  # E0, -E2, -E8, -E4, -E5
        "vehicles": [
            {"type": "truck", "count": 1},
            {"type": "car", "count": 2},
            {"type": "lorry", "count": 1},
            {"type": "bus", "count": 1},
            {"type": "auto", "count": 1},
            {"type": "bike", "count": 5},
        ]
    }
}
result = collection.insert_one(normal_record)
print(f"Added normal vehicles: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(normal_record['timestamp'])}")

# police_record = {
#     "timestamp": get_bson_timestamp(6),
#     "type": "emergency_vehicle",
#     "data": {
#         "vehicle_type": "police",
#         "entryPoint": "-E5"  # E0, -E2, -E8, -E4, -E5
#     }
# }
# result = collection.insert_one(police_record)
# print(f"Added police vehicle: {result.inserted_id}")
# print(f"  Timestamp: {to_iso_display(police_record['timestamp'])}")

# fireTruck_record = {
#     "timestamp": get_bson_timestamp(6),
#     "type": "emergency_vehicle",
#     "data": {
#         "vehicle_type": "firetruck",
#         "entryPoint": "-E8"  # E0, -E2, -E8, -E4, -E5
#     }
# }
# result = collection.insert_one(fireTruck_record)
# print(f"Added firetruck vehicle: {result.inserted_id}")
# print(f"  Timestamp: {to_iso_display(fireTruck_record['timestamp'])}")

print("\n" + "="*60)
print("TEST DATA ADDED SUCCESSFULLY!")
print("="*60)
print("\nRecords in database:")
for doc in collection.find().sort("timestamp", pymongo.ASCENDING):
    print(f"  - Type: {doc['type']}")
    ts = doc.get('timestamp')
    if isinstance(ts, datetime):
        ts_text = to_iso_display(ts)
    else:
        ts_text = str(ts)
    print(f"    Timestamp: {ts_text}")
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