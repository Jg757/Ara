"""
Knowledge Base Module for Ara
Stores and retrieves personal documents using ChromaDB vector database.
"""

import chromadb
import hashlib
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

CHROMA_DIR = "chroma_db"
DOCUMENTS_COLLECTION = "ara_documents"

class KnowledgeBase:
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
            name=DOCUMENTS_COLLECTION,
            metadata={"description": "Ara's document knowledge base"}
        )
        print(f"[KnowledgeBase] Initialized with {self._collection.count()} documents")
    
    def _generate_chunk_id(self, doc_name: str, chunk_index: int) -> str:
        """Generate unique ID for document chunk."""
        content = f"{doc_name}:chunk:{chunk_index}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Split text into overlapping chunks for better retrieval."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start = end - overlap
        return chunks
    
    def add_document(self, name: str, content: str, doc_type: str = "text") -> int:
        """
        Add a document to the knowledge base.
        Returns number of chunks stored.
        """
        if not content or not content.strip():
            return 0
        
        # Remove existing document with same name
        self.delete_document(name)
        
        # Chunk the document
        chunks = self._chunk_text(content)
        
        # Store each chunk
        for i, chunk in enumerate(chunks):
            chunk_id = self._generate_chunk_id(name, i)
            self._collection.add(
                documents=[chunk],
                metadatas=[{
                    "doc_name": name,
                    "doc_type": doc_type,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "added_at": datetime.now().isoformat()
                }],
                ids=[chunk_id]
            )
        
        print(f"[KnowledgeBase] Added '{name}' ({len(chunks)} chunks)")
        return len(chunks)
    
    def search(self, query: str, n_results: int = 5) -> List[Dict]:
        """
        Search for relevant document chunks.
        Returns list of dicts with doc_name, chunk, and metadata.
        """
        if self._collection.count() == 0:
            return []
        
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        docs = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i]
                docs.append({
                    "doc_name": metadata.get("doc_name", "Unknown"),
                    "doc_type": metadata.get("doc_type", "text"),
                    "chunk": doc,
                    "chunk_index": metadata.get("chunk_index", 0),
                    "total_chunks": metadata.get("total_chunks", 1)
                })
        
        return docs
    
    def get_relevant_context(self, query: str, n_results: int = 5) -> str:
        """
        Search and return formatted context string for Ara.
        """
        docs = self.search(query, n_results)
        if not docs:
            return ""
        
        # Group by document
        by_doc = {}
        for doc in docs:
            name = doc["doc_name"]
            if name not in by_doc:
                by_doc[name] = []
            by_doc[name].append(doc["chunk"])
        
        context = "\n[Relevant Documents]:\n"
        for name, chunks in by_doc.items():
            context += f"\n--- From '{name}' ---\n"
            context += "\n".join(chunks[:3])  # Max 3 chunks per doc
            context += "\n"
        
        return context
    
    def list_documents(self) -> List[Dict]:
        """List all stored documents (unique names)."""
        if self._collection.count() == 0:
            return []
        
        # Get all metadata
        all_data = self._collection.get()
        
        docs = {}
        for metadata in all_data['metadatas']:
            name = metadata.get("doc_name", "Unknown")
            if name not in docs:
                docs[name] = {
                    "name": name,
                    "type": metadata.get("doc_type", "text"),
                    "chunks": metadata.get("total_chunks", 1),
                    "added_at": metadata.get("added_at", "")
                }
        
        return list(docs.values())
    
    def delete_document(self, name: str) -> int:
        """Delete all chunks of a document by name. Returns count deleted."""
        if self._collection.count() == 0:
            return 0
        
        # Find all chunk IDs for this document
        all_data = self._collection.get()
        ids_to_delete = []
        
        for i, metadata in enumerate(all_data['metadatas']):
            if metadata.get("doc_name") == name:
                ids_to_delete.append(all_data['ids'][i])
        
        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
            print(f"[KnowledgeBase] Deleted '{name}' ({len(ids_to_delete)} chunks)")
        
        return len(ids_to_delete)
    
    def count(self) -> int:
        """Return total number of chunks stored."""
        return self._collection.count()


# Convenience functions
def init_knowledge_base() -> KnowledgeBase:
    """Initialize and return the knowledge base instance."""
    return KnowledgeBase.get_instance()

def add_document(name: str, content: str, doc_type: str = "text") -> int:
    """Add a document to the knowledge base."""
    kb = KnowledgeBase.get_instance()
    return kb.add_document(name, content, doc_type)

def search_documents(query: str, n_results: int = 5) -> str:
    """Search documents and return formatted context."""
    kb = KnowledgeBase.get_instance()
    return kb.get_relevant_context(query, n_results)

def list_documents() -> List[Dict]:
    """List all stored documents."""
    kb = KnowledgeBase.get_instance()
    return kb.list_documents()

def delete_document(name: str) -> int:
    """Delete a document by name."""
    kb = KnowledgeBase.get_instance()
    return kb.delete_document(name)


if __name__ == "__main__":
    import sys
    
    kb = init_knowledge_base()
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "list":
            docs = kb.list_documents()
            if docs:
                print(f"\nStored Documents ({len(docs)}):\n")
                for doc in docs:
                    print(f"  - {doc['name']} ({doc['type']}, {doc['chunks']} chunks)")
            else:
                print("No documents stored.")
        
        elif cmd == "search" and len(sys.argv) > 2:
            query = " ".join(sys.argv[2:])
            print(f"\nSearching for: {query}\n")
            print(kb.get_relevant_context(query))
        
        elif cmd == "delete" and len(sys.argv) > 2:
            name = " ".join(sys.argv[2:])
            count = kb.delete_document(name)
            print(f"Deleted {count} chunks.")
        
        elif cmd == "count":
            print(f"Total chunks stored: {kb.count()}")
        
        else:
            print("Usage: python knowledge_base.py [list|search <query>|delete <name>|count]")
    else:
        print("Usage: python knowledge_base.py [list|search <query>|delete <name>|count]")
