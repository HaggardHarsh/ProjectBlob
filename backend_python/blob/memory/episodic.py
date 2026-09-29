import time
from typing import List, Dict

class EpisodicMemory:
    def __init__(self, vector_store):
        self.vector_store = vector_store
        
    def add_episode(self, user_msg: str, blob_msg: str, context: dict = None):
        """Stores a chat turn as an episodic memory."""
        text = f"User: {user_msg}\nBlob: {blob_msg}"
        metadata = {
            "type": "episodic",
            "timestamp": time.time(),
            "consolidated": False,
        }
        if context:
            # Flatten context for metadata storage (Chroma only accepts int/float/str/bool)
            for k, v in context.items():
                if isinstance(v, (int, float, str, bool)):
                    metadata[f"ctx_{k}"] = v
                
        self.vector_store.store(text, metadata, collection="episodic")
        
    def recall_relevant(self, query: str, top_k: int = 5,
                        max_distance: float | None = None,
                        min_timestamp: float | None = None) -> List[Dict]:
        """Recalls most relevant recent episodes using vector search and decay."""
        return self.vector_store.recall(query, top_k=top_k, collection="episodic",
                                        max_distance=max_distance, min_timestamp=min_timestamp)
