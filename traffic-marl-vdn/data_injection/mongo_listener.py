"""
MongoDB Listener for real-time data injection into SUMO.
Primary timestamp format is MongoDB Date/BSON datetime.
"""
import pymongo
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Union, Optional
from bson import ObjectId

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MongoDBListener:
    """Listens to MongoDB for new injection records"""
    
    def __init__(self, 
                 connection_string: str = "mongodb+srv://rolexultimate23_db_user:qwerty12345@cluster0.axqeteq.mongodb.net/?appName=Cluster0",
                 database: str = "EmergencyDetection",
                 collection: str = "SUMOinjections",
                 poll_interval: float = 1.0):
        
        self.connection_string = connection_string
        self.database_name = database
        self.collection_name = collection
        self.poll_interval = poll_interval
        self.checkpoint_collection_name = "_listener_checkpoints"
        
        # Connect to MongoDB Atlas
        try:
            self.client = pymongo.MongoClient(connection_string)
            self.db = self.client[database]
            self.collection = self.db[collection]
            self.checkpoint_collection = self.db[self.checkpoint_collection_name]
            
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB Atlas")
            logger.info(f"Database: {database}, Collection: {collection}")

            # Load or create checkpoint
            self._load_or_create_checkpoint()
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        
        self.processed_ids = set()  # Track processed document IDs during this session
        
        # Statistics
        self.stats = {
            'total_polled': 0,
            'emergency_vehicles': 0,
            'pedestrians': 0,
            'normal_vehicles': 0,
            'last_poll_time': None
        }
    
    def _to_numeric_timestamp(self, raw_timestamp: Union[str, int, float, datetime]) -> Optional[float]:
        """Convert supported timestamp formats to epoch seconds."""
        try:
            if isinstance(raw_timestamp, datetime):
                # Support MongoDB Date/BSON datetime values directly.
                if raw_timestamp.tzinfo is None:
                    raw_timestamp = raw_timestamp.replace(tzinfo=timezone.utc)
                return raw_timestamp.timestamp()

            if isinstance(raw_timestamp, (int, float)):
                return float(raw_timestamp)

            if isinstance(raw_timestamp, str):
                ts = raw_timestamp.strip()

                # Numeric timestamp encoded as string.
                try:
                    return float(ts)
                except ValueError:
                    pass

                # ISO 8601 with timezone offset (e.g., +05:30) or trailing Z.
                try:
                    normalized = ts.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(normalized)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    pass

            return None

        except Exception as e:
            logger.debug(f"Error converting timestamp '{raw_timestamp}': {e}")
            return None
    
    def _numeric_to_iso(self, numeric_timestamp: float) -> str:
        """Convert numeric timestamp to ISO format for display"""
        dt = datetime.fromtimestamp(numeric_timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
    
    def _load_or_create_checkpoint(self):
        """Load last processed ObjectId from checkpoint or initialize new one"""
        checkpoint_key = f"{self.database_name}:{self.collection_name}"
        
        try:
            checkpoint_doc = self.checkpoint_collection.find_one({"_id": checkpoint_key})
            
            if checkpoint_doc and "last_processed_id" in checkpoint_doc:
                self.start_object_id = checkpoint_doc["last_processed_id"]
                logger.info(
                    "Loaded checkpoint: will process documents with _id > %s",
                    str(self.start_object_id)
                )
            else:
                # First time: use current time, effectively ignoring all existing documents
                startup_utc = datetime.now(timezone.utc)
                self.start_object_id = ObjectId.from_datetime(startup_utc)
                logger.info(
                    "No previous checkpoint found. Created new checkpoint at ObjectId > %s (%s). "
                    "All existing documents will be skipped.",
                    str(self.start_object_id),
                    startup_utc.isoformat(),
                )
                # Create initial checkpoint
                self.checkpoint_collection.update_one(
                    {"_id": checkpoint_key},
                    {"$set": {"last_processed_id": self.start_object_id}},
                    upsert=True
                )
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}. Starting fresh.")
            startup_utc = datetime.now(timezone.utc)
            self.start_object_id = ObjectId.from_datetime(startup_utc)
        
        # Start from current wall-clock time for diagnostic display
        self.last_timestamp = time.time()
    
    def _save_checkpoint(self, last_processed_id: ObjectId):
        """Save the last processed ObjectId to checkpoint"""
        checkpoint_key = f"{self.database_name}:{self.collection_name}"
        
        try:
            self.checkpoint_collection.update_one(
                {"_id": checkpoint_key},
                {"$set": {
                    "last_processed_id": last_processed_id,
                    "last_updated": datetime.now(timezone.utc)
                }},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")
    
    def get_new_records(self) -> List[Dict[str, Any]]:
        """
        Poll for new records since last checkpoint.
        Returns list of new records.
        """
        try:
            # Query for documents with _id > last checkpoint
            query = {'_id': {'$gt': self.start_object_id}}
            all_records = list(self.collection.find(query).sort('_id', pymongo.ASCENDING))
            
            new_records = []
            last_processed_id = self.start_object_id
            
            for doc in all_records:
                # Skip if already processed in this session
                if doc['_id'] in self.processed_ids:
                    continue
                
                # Get timestamp from document (ISO or numeric) - for diagnostics only
                doc_raw_time = doc.get('timestamp')
                if doc_raw_time is None:
                    doc_time = None
                else:
                    doc_time = self._to_numeric_timestamp(doc_raw_time)
                
                # Accept all post-checkpoint documents
                new_records.append(doc)
                self.processed_ids.add(doc['_id'])
                last_processed_id = doc['_id']

                # Keep timestamp only for diagnostic printouts
                if doc_time is not None and doc_time > self.last_timestamp:
                    self.last_timestamp = doc_time

                # Update statistics
                self.stats['total_polled'] += 1
                if doc.get('type') == 'emergency_vehicle':
                    self.stats['emergency_vehicles'] += 1
                elif doc.get('type') == 'pedestrian':
                    self.stats['pedestrians'] += 1
                elif doc.get('type') == 'normal_vehicle':
                    self.stats['normal_vehicles'] += 1

                logger.debug(f"New record found: {doc.get('type')} at {doc_raw_time}")
            
            self.stats['last_poll_time'] = datetime.now()
            
            if new_records:
                logger.info(f"Total new records this poll: {len(new_records)}")
                # Save checkpoint after successfully processing records
                self._save_checkpoint(last_processed_id)
            
            return new_records
            
        except Exception as e:
            logger.error(f"Error polling MongoDB: {e}")
            return []
    
    def print_stats(self):
        """Print polling statistics"""
        logger.info("\n" + "="*50)
        logger.info("MongoDB Polling Statistics:")
        logger.info(f"   Total records polled: {self.stats['total_polled']}")
        logger.info(f"   Emergency vehicles: {self.stats['emergency_vehicles']}")
        logger.info(f"   Pedestrians: {self.stats['pedestrians']}")
        logger.info(f"   Normal vehicles: {self.stats['normal_vehicles']}")
        logger.info(f"   Last poll: {self.stats['last_poll_time']}")
        logger.info(f"   Last timestamp: {self._numeric_to_iso(self.last_timestamp)}")
        logger.info("="*50)
    
    def close(self):
        """Close MongoDB connection"""
        if hasattr(self, 'client'):
            # Save final checkpoint before closing
            if hasattr(self, 'start_object_id') and self.processed_ids:
                # Find the max ObjectId we've processed
                max_processed_id = max(self.processed_ids)
                self._save_checkpoint(max_processed_id)
                logger.info(f"Final checkpoint saved with processed _id: {max_processed_id}")
            
            self.print_stats()
            self.client.close()
            logger.info("MongoDB connection closed")