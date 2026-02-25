import json
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

logger = logging.getLogger("voice-agent")

MEMORY_FILE = "agent_memory.json"
PROFILE_FILE = "user_profile.json"
GCS_BUCKET = os.getenv("GCS_BUCKET")  # Set in Cloud Run, empty locally

# Cloud Storage support
def get_gcs_client():
    """Get Google Cloud Storage client (lazy loaded)"""
    try:
        from google.cloud import storage
        return storage.Client()
    except Exception as e:
        logger.error(f"Failed to create GCS client: {e}")
        return None

class MemoryManager:
    @staticmethod
    def load_memory() -> str:
        """Loads usage history and summarizes it for context injection."""
        history = []
        
        if GCS_BUCKET:
            # Load from Cloud Storage
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(MEMORY_FILE)
                    if blob.exists():
                        content = blob.download_as_string()
                        history = json.loads(content)
                        logger.info(f"Loaded memory from GCS: {len(history)} turns")
            except Exception as e:
                logger.error(f"Failed to load memory from GCS: {e}")
        else:
            # Load from local file
            if os.path.exists(MEMORY_FILE):
                try:
                    with open(MEMORY_FILE, "r") as f:
                        history = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load memory: {e}")
        
        if not history:
            return ""
        
        recent = history[-20:]  # Keep last 20 turns for direct context
        memory_str = "\n[Recent Conversation Flow]:\n"
        for turn in recent:
            memory_str += f"{turn['role']}: {turn['text']}\n"
        
        return memory_str
        
    @staticmethod
    def load_user_profile() -> str:
        """Loads extracted core facts about the user."""
        profile_data = {"facts": []}
        
        if GCS_BUCKET:
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(PROFILE_FILE)
                    if blob.exists():
                        content = blob.download_as_string()
                        profile_data = json.loads(content)
            except Exception as e:
                logger.error(f"Failed to load profile from GCS: {e}")
        else:
            if os.path.exists(PROFILE_FILE):
                try:
                    with open(PROFILE_FILE, "r") as f:
                        profile_data = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load profile: {e}")
                    
        facts = profile_data.get("facts", [])
        if not facts:
            return ""
            
        profile_str = "\n[Core Facts About User]:\n"
        for fact in facts:
            profile_str += f"- {fact['attribute']}: {fact['value']}\n"
        return profile_str
        
    @staticmethod
    def add_facts_to_profile(new_facts: list):
        """Appends new extracted facts to the user profile."""
        if not new_facts:
            return
            
        profile_data = {"facts": []}
        
        # Load existing
        if GCS_BUCKET:
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(PROFILE_FILE)
                    if blob.exists():
                        content = blob.download_as_string()
                        profile_data = json.loads(content)
            except Exception as e:
                pass
        else:
            if os.path.exists(PROFILE_FILE):
                try:
                    with open(PROFILE_FILE, "r") as f:
                        profile_data = json.load(f)
                except:
                    pass
                    
        # Filter duplicates based on attribute (update existing, add new)
        existing_facts = {f["attribute"].lower(): f for f in profile_data.get("facts", [])}
        
        for fact in new_facts:
            attr = fact.get("attribute", "").lower()
            if attr:
                existing_facts[attr] = fact # Overwrite or add
                
        profile_data["facts"] = list(existing_facts.values())
        
        # Save
        try:
            if GCS_BUCKET:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(PROFILE_FILE)
                    blob.upload_from_string(json.dumps(profile_data, indent=2))
            else:
                with open(PROFILE_FILE, "w") as f:
                    json.dump(profile_data, f, indent=2)
            logger.info(f"Updated user profile with {len(new_facts)} facts")
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")

    @staticmethod
    def get_last_interaction_time() -> str:
        """Get the timestamp of the last user turn from memory.
        Returns ISO format string or None if no history."""
        history = []
        
        if GCS_BUCKET:
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(MEMORY_FILE)
                    if blob.exists():
                        content = blob.download_as_string()
                        history = json.loads(content)
            except Exception as e:
                logger.error(f"Failed to read from GCS: {e}")
        else:
            if os.path.exists(MEMORY_FILE):
                try:
                    with open(MEMORY_FILE, "r") as f:
                        history = json.load(f)
                except:
                    pass
        
        if not history:
            return None
        
        # Search backwards for the last entry with a timestamp
        for entry in reversed(history):
            if 'timestamp' in entry:
                return entry['timestamp']
        
        return None

    @staticmethod
    def save_turn(role: str, text: str):
        """Appends a single turn to the memory file."""
        entry = {"role": role, "text": text, "timestamp": datetime.now(EASTERN).isoformat()}
        history = []
        
        if GCS_BUCKET:
            # Read from Cloud Storage
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(MEMORY_FILE)
                    if blob.exists():
                        content = blob.download_as_string()
                        history = json.loads(content)
            except Exception as e:
                logger.error(f"Failed to read from GCS: {e}")
            
            # Append and save to Cloud Storage
            history.append(entry)
            try:
                client = get_gcs_client()
                if client:
                    bucket = client.bucket(GCS_BUCKET)
                    blob = bucket.blob(MEMORY_FILE)
                    blob.upload_from_string(json.dumps(history, indent=2))
            except Exception as e:
                logger.error(f"Failed to save to GCS: {e}")
        else:
            # Read from local file
            if os.path.exists(MEMORY_FILE):
                try:
                    with open(MEMORY_FILE, "r") as f:
                        history = json.load(f)
                except:
                    history = []
            
            # Append and save locally
            history.append(entry)
            try:
                with open(MEMORY_FILE, "w") as f:
                    json.dump(history, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save memory: {e}")
