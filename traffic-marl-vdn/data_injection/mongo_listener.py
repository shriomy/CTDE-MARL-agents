"""
MongoDB Listener for real-time data injection into SUMO.
Supports both Unix numeric and ISO 8601 timestamps in SUMOinjections.
"""
import pymongo
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Union, Optional

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
        
        # Connect to MongoDB Atlas
        try:
            self.client = pymongo.MongoClient(connection_string)
            self.db = self.client[database]
            self.collection = self.db[collection]
            
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB Atlas")
            logger.info(f"   Database: {database}, Collection: {collection}")
            
            # Start from current wall-clock time so restarts only process NEW inserts.
            self.last_timestamp = time.time()
            logger.info(
                "   Startup checkpoint set to now: %s (numeric: %.3f). Existing records will be ignored.",
                self._numeric_to_iso(self.last_timestamp),
                self.last_timestamp,
            )
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        
        self.processed_ids = set()  # Track processed document IDs
        
        # Statistics
        self.stats = {
            'total_polled': 0,
            'emergency_vehicles': 0,
            'pedestrians': 0,
            'normal_vehicles': 0,
            'last_poll_time': None
        }
    
    def _to_numeric_timestamp(self, raw_timestamp: Union[str, int, float]) -> Optional[float]:
        """Convert supported timestamp formats to epoch seconds."""
        try:
            if isinstance(raw_timestamp, (int, float)):
                return float(raw_timestamp)

            if isinstance(raw_timestamp, str):
                ts = raw_timestamp.strip()

                # Numeric timestamp encoded as string.
                try:
                    return float(ts)
                except ValueError:
                    pass

                # ISO 8601 with timezone suffix like +00:00.
                if '+' in ts:
                    dt_str = ts.split('+')[0]
                    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%f")
                    dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()

                # ISO 8601 with trailing Z.
                if ts.endswith('Z'):
                    dt = datetime.strptime(ts[:-1], "%Y-%m-%dT%H:%M:%S.%f")
                    dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()

            logger.warning(f"Unsupported timestamp format: {raw_timestamp}")
            return None

        except Exception as e:
            logger.error(f"Error converting timestamp '{raw_timestamp}': {e}")
            return None
    
    def _numeric_to_iso(self, numeric_timestamp: float) -> str:
        """Convert numeric timestamp to ISO format for display"""
        dt = datetime.fromtimestamp(numeric_timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
    
    def get_new_records(self) -> List[Dict[str, Any]]:
        """
        Poll for new records since last timestamp.
        Returns list of new records.
        """
        try:
            # Get all records (we'll filter by timestamp ourselves)
            all_records = list(self.collection.find().sort("timestamp", pymongo.ASCENDING))
            
            new_records = []
            
            for doc in all_records:
                # Skip if already processed
                if doc['_id'] in self.processed_ids:
                    continue
                
                # Get timestamp from document (ISO or numeric)
                doc_raw_time = doc.get('timestamp')
                if doc_raw_time is None:
                    continue
                
                # Convert to numeric for comparison
                doc_time = self._to_numeric_timestamp(doc_raw_time)
                if doc_time is None:
                    continue
                
                # Only include if after our last timestamp
                if doc_time > self.last_timestamp:
                    new_records.append(doc)
                    self.processed_ids.add(doc['_id'])
                    
                    # Update last timestamp
                    if doc_time > self.last_timestamp:
                        self.last_timestamp = doc_time
                    
                    # Update statistics
                    self.stats['total_polled'] += 1
                    if doc.get('type') == 'emergency_vehicle':
                        self.stats['emergency_vehicles'] += 1
                    elif doc.get('type') == 'pedestrian':
                        self.stats['pedestrians'] += 1
                    elif doc.get('type') == 'normal_vehicle':
                        self.stats['normal_vehicles'] += 1
                    
                    logger.info(f"New record found: {doc.get('type')} at {doc_raw_time}")
            
            self.stats['last_poll_time'] = datetime.now()
            
            if new_records:
                logger.info(f"Total new records this poll: {len(new_records)}")
            
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
            self.print_stats()
            self.client.close()
            logger.info("MongoDB connection closed")