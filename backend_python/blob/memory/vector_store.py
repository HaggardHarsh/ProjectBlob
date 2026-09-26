import chromadb
import asyncio
import logging
import uuid
import time
from blob.memory.decay import DecayAlgorithm

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, db_path: str):
        self.client = chromadb.PersistentClient(path=db_path)
        self.episodic = self.client.get_or_create_collection("episodic")
        self.semantic = self.client.get_or_create_collection("semantic")
        self.decay_algo = DecayAlgorithm()
        self.memory_id_counter = 0

    def store(self, text: str, metadata: dict, collection: str = "episodic"):
        doc_id = str(uuid.uuid4())
        col = self.semantic if collection == "semantic" else self.episodic
        
        # Add tracking metadata for decay algorithm
        metadata["last_accessed"] = time.time()
        metadata["access_count"] = 1
        
        col.add(documents=[text], metadatas=[metadata], ids=[doc_id])
        return doc_id
        
    def recall(self, query: str, top_k: int = 5, collection: str = "episodic") -> list:
        col = self.semantic if collection == "semantic" else self.episodic
        results = col.query(query_texts=[query], n_results=top_k * 2) # Get extra for decay re-ranking
        
        if not results['documents'] or not results['documents'][0]:
            return []
            
        recalled = []
        current_time = time.time()
        
        for doc, meta, id_, dist in zip(results['documents'][0], results['metadatas'][0], results['ids'][0], results['distances'][0]):
            # distance in chroma: lower is better (more similar). Let's invert it for score.
            base_sim = max(0, 1.0 - dist)
            
            last_accessed = meta.get("last_accessed", current_time)
            access_count = meta.get("access_count", 1)
            days_since = (current_time - last_accessed) / (60*60*24)
            
            score = self.decay_algo.calculate_score(base_sim, days_since, access_count)
            recalled.append({"id": id_, "text": doc, "metadata": meta, "score": score})
            
            # Update metadata
            meta["last_accessed"] = current_time
            meta["access_count"] = access_count + 1
            col.update(ids=[id_], metadatas=[meta])
            
        # Sort by decay-adjusted score
        recalled.sort(key=lambda x: x["score"], reverse=True)
        return recalled[:top_k]

    def delete(self, memory_id: str, collection: str = "episodic"):
        col = self.semantic if collection == "semantic" else self.episodic
        col.delete(ids=[memory_id])
