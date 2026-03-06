from pymongo import MongoClient
import time

# Your Atlas connection string
uri = "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0"

print("Testing MongoDB Atlas connection...")
print(f"URI: {uri.replace('qwerty12345', '********')}")  # Hide password

try:
    # Connect with timeout
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    
    # Force connection to verify
    client.admin.command('ping')
    print("✅ Successfully connected to MongoDB Atlas!")
    
    # List databases
    dbs = client.list_database_names()
    print(f"Available databases: {dbs}")
    
    # Check our specific database
    db = client['EmergencyDetection']
    collections = db.list_collection_names()
    print(f"Collections in EmergencyDetection: {collections}")
    
    # Check SUMOinjections collection
    if 'SUMOinjections' in collections:
        count = db.SUMOinjections.count_documents({})
        print(f"📊 Documents in SUMOinjections: {count}")
        
        # Show sample document
        sample = db.SUMOinjections.find_one()
        if sample:
            print("\nSample document:")
            print(f"  _id: {sample.get('_id')}")
            print(f"  type: {sample.get('type')}")
            print(f"  timestamp: {sample.get('timestamp')}")
            print(f"  data: {sample.get('data')}")
    else:
        print("⚠️  SUMOinjections collection doesn't exist yet")
        
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("\nPossible issues:")
    print("1. Your IP address might not be whitelisted in Atlas")
    print("2. Username/password might be incorrect")
    print("3. Internet connection issues")
    print("\nTo fix IP whitelist:")
    print("1. Go to https://cloud.mongodb.com")
    print("2. Login to your cluster")
    print("3. Go to Network Access")
    print("4. Add your current IP address")
finally:
    if 'client' in locals():
        client.close()