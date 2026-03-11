"""
Add test data with IST ISO-8601 timestamps to MongoDB.
Timestamps are stored in the same `timestamp` field as strings with +05:30.
"""
import pymongo
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# MongoDB connection
client = pymongo.MongoClient("mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0")
db = client["EmergencyDetection"]
collection = db["SUMOinjections"]

# print("Clearing old test data...")
# collection.delete_many({})  # Clear all for clean test

print("Adding test data with IST timestamps (+05:30)...")

inserted_ids = []

def get_ist_timestamp(offset_seconds=0):
    """Get IST timestamp string with explicit +05:30 offset."""
    dt = datetime.now(IST) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+05:30"


def to_iso_display(dt):
    """Render datetime as ISO string in IST (+05:30) for console logs only."""
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(IST)
    return local_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+05:30"

normal_record = {
    "timestamp": get_ist_timestamp(4),  # 4 seconds later
    "type": "normal_vehicle",
    "data": {
        "entryPoint": "-E5",  # E0, -E2, -E8, -E4, -E5
        "vehicles": [
            {"type": "truck", "count": 2},
            {"type": "car", "count": 10},
            {"type": "lorry", "count": 4},
            {"type": "bus", "count": 10},
            {"type": "auto", "count": 10},
            {"type": "bike", "count": 30},
        ]
    }
}
result = collection.insert_one(normal_record)
inserted_ids.append(result.inserted_id)
print(f"Added normal vehicles: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(normal_record['timestamp'])}")

pedestrian_record = {
    "timestamp": get_ist_timestamp(2),  # 2 seconds later
    "type": "pedestrian",
    "data": {
        "pedestrians": [
            {"type": "elderly", "position": "south_side", "count": 5},  
            {"type": "student", "position": "north_side", "count":10},      
            {"type": "adult", "position": "south_side", "count": 8},        
            {"type": "mobility_aid", "position": "north_side", "count": 2},   
        ]
    }
}
result = collection.insert_one(pedestrian_record)
inserted_ids.append(result.inserted_id)
print(f"Added pedestrians: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(pedestrian_record['timestamp'])}")

emergency_record = {
    "timestamp": get_ist_timestamp(0),
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "ambulance",
        "entryPoint": "-E4"  # E0, -E2, -E8, -E4, -E5
    }
}
result = collection.insert_one(emergency_record)
inserted_ids.append(result.inserted_id)
print(f"Added emergency vehicle: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(emergency_record['timestamp'])}")

police_record = {
    "timestamp": get_ist_timestamp(6),
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "police",
        "entryPoint": "-E0"  # E0, -E2, -E8, -E4, -E5
    }
}
result = collection.insert_one(police_record)
inserted_ids.append(result.inserted_id)
print(f"Added police vehicle: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(police_record['timestamp'])}")

fireTruck_record = {
    "timestamp": get_ist_timestamp(6),
    "type": "emergency_vehicle",
    "data": {
        "vehicle_type": "firetruck",
        "entryPoint": "-E2"  # E0, -E2, -E8, -E4, -E5
    }
}
result = collection.insert_one(fireTruck_record)
inserted_ids.append(result.inserted_id)
print(f"Added firetruck vehicle: {result.inserted_id}")
print(f"  Timestamp: {to_iso_display(fireTruck_record['timestamp'])}")

print("\nRecords inserted in this run:")
query = {"_id": {"$in": inserted_ids}}
for doc in collection.find(query).sort("timestamp", pymongo.ASCENDING):
    # print(f"  - Type: {doc['type']}")
    ts = doc.get('timestamp')
    if isinstance(ts, datetime):
        ts_text = to_iso_display(ts)
    else:
        ts_text = str(ts)
    # print(f"    Timestamp: {ts_text}")
    if doc['type'] == 'emergency_vehicle':
        print(f"    Vehicle: {doc['data']['vehicle_type']} at {doc['data']['entryPoint']}")
    elif doc['type'] == 'normal_vehicle':
        vehicles = doc['data'].get('vehicles', [])
        summary = ", ".join(f"{v.get('type')}={v.get('count')}" for v in vehicles)
        print(f"    Vehicles: [{summary}] at {doc['data']['entryPoint']}")
    elif doc['type'] == 'pedestrian':
        total = sum(p['count'] for p in doc['data']['pedestrians'])
        print(f"    Total pedestrians: {total}")

# print(f"\nTotal records currently in collection: {collection.count_documents({})}")

# Close connection
client.close()