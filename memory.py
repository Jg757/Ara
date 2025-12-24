import json
import os
import logging

logger = logging.getLogger("voice-agent")

MEMORY_FILE = "agent_memory.json"
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
        
        recent = history[-500:]  # Keep last 500 turns for long-term memory
        memory_str = "\n[Previous Conversation Memory]:\n"
        for turn in recent:
            memory_str += f"{turn['role']}: {turn['text']}\n"
        
        return memory_str

    @staticmethod
    def save_turn(role: str, text: str):
        """Appends a single turn to the memory file."""
        entry = {"role": role, "text": text}
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
