"""
Vector Memory Module for Ara
Uses ChromaDB for semantic search over conversation history.
"""

import chromadb
from chromadb.config import Settings
import json
import os
import hashlib
from typing import List, Tuple

MEMORY_FILE = "agent_memory.json"
CHROMA_DIR = "chroma_db"

class VectorMemory:
    _instance = None
    _client = None
    _collection = None
    
    @classmethod
    def get_instance(cls):
        """Singleton pattern for ChromaDB client."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize ChromaDB client and collection."""
        self._client = chromadb.PersistentClient(path=CHROMA_DIR)
        self._collection = self._client.get_or_create_collection(
            name="ara_memories",
            metadata={"description": "Ara's conversation memories"}
        )
        print(f"[VectorMemory] Initialized with {self._collection.count()} memories")
    
    def _generate_id(self, text: str, role: str) -> str:
        """Generate a unique ID for a memory entry."""
        content = f"{role}:{text}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def add_memory(self, role: str, text: str):
        """
        Adds a single memory. 
        Note: In the chunked system, single-line adds are less useful for context.
        We will rely primarily on batch indexing or chunking at the bridge level.
        For now, this just adds the single line so live memory works somewhat, 
        but index_all_memories provides the true overlapping chunks.
        """
        if not text or not text.strip():
            return
            
        memory_id = self._generate_id(text, role)
        
        # Check if already exists
        existing = self._collection.get(ids=[memory_id])
        if existing and existing['ids']:
            return  # Already indexed
        
        self._collection.add(
            documents=[text],
            metadatas=[{"role": role, "type": "single"}],
            ids=[memory_id]
        )
    
    def index_all_memories(self, chunk_size=5, overlap=2):
        """
        Index all memories from the JSON file into ChromaDB in overlapping chunks.
        chunk_size: number of turns per chunk
        overlap: number of turns to overlap with the previous chunk
        """
        if not os.path.exists(MEMORY_FILE):
            print("[VectorMemory] No memory file found")
            return 0
            
        with open(MEMORY_FILE, "r") as f:
            history = json.load(f)
        
        if not history:
            print("[VectorMemory] Memory file is empty")
            return 0
        
        # Clear existing collection and re-add everything (faster than per-entry duplicate check)
        try:
            self._client.delete_collection("ara_memories")
            self._collection = self._client.get_or_create_collection(
                name="ara_memories",
                metadata={"description": "Ara's conversation memories"}
            )
        except Exception as e:
            print(f"[VectorMemory] Error resetting collection: {e}")
        
        # Create overlapping chunks
        documents = []
        metadatas = []
        ids = []
        
        step = max(1, chunk_size - overlap)
        
        for i in range(0, len(history), step):
            chunk = history[i:i + chunk_size]
            if not chunk:
                break
                
            # Combine the turns into a single narrative block
            chunk_text = "\n".join([f"{turn.get('role', 'unknown')}: {turn.get('text', '')}" for turn in chunk if turn.get('text', '').strip()])
            
            if not chunk_text.strip():
                continue
                
            # Use the first timestamp or a hash of the text for ID
            chunk_id = hashlib.md5(chunk_text.encode()).hexdigest()
            
            if chunk_id not in ids:
                documents.append(chunk_text)
                metadatas.append({"role": "context_chunk", "type": "chunk"})
                ids.append(chunk_id)
        
        # Batch add in chunks of 50
        added = 0
        batch_size = 50
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i:i+batch_size]
            batch_meta = metadatas[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            try:
                self._collection.add(
                    documents=batch_docs,
                    metadatas=batch_meta,
                    ids=batch_ids
                )
                added += len(batch_docs)
            except Exception as e:
                print(f"[VectorMemory] Batch add error at {i}: {e}")
        
        print(f"[VectorMemory] Indexed {added} memories (total: {self._collection.count()})")
        return added
    
    def search(self, query: str, n_results: int = 10) -> List[Tuple[str, str]]:
        """
        Search for relevant memories.
        Returns list of (role, text) tuples.
        """
        if self._collection.count() == 0:
            return []
            
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        memories = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                role = results['metadatas'][0][i].get('role', 'user')
                memories.append((role, doc))
        
        return memories
    
    def get_relevant_context(self, query: str, n_results: int = 10) -> str:
        """
        Get relevant memories formatted as context string.
        """
        memories = self.search(query, n_results)
        if not memories:
            return ""
        
        context = "\n[Relevant Past Memories]:\n"
        for role, text in memories:
            if role == "context_chunk":
                context += f"---\n{text}\n---\n"
            else:
                context += f"{role}: {text}\n"
        
        return context


# Convenience functions
def init_vector_memory() -> VectorMemory:
    """Initialize and return the vector memory instance."""
    return VectorMemory.get_instance()

def search_memories(query: str, n_results: int = 10) -> str:
    """Search memories and return formatted context."""
    vm = VectorMemory.get_instance()
    return vm.get_relevant_context(query, n_results)

def add_memory(role: str, text: str):
    """Add a memory to the vector store."""
    vm = VectorMemory.get_instance()
    vm.add_memory(role, text)

def reindex_all():
    """Reindex all memories from JSON file."""
    vm = VectorMemory.get_instance()
    return vm.index_all_memories()


if __name__ == "__main__":
    # CLI for testing/indexing
    import sys
    
    vm = init_vector_memory()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "index":
            vm.index_all_memories()
        elif sys.argv[1] == "search":
            query = " ".join(sys.argv[2:])
            print(f"\nSearching for: {query}\n")
            print(vm.get_relevant_context(query))
        elif sys.argv[1] == "count":
            print(f"Total memories indexed: {vm._collection.count()}")
    else:
        print("Usage: python vector_memory.py [index|search <query>|count]")
