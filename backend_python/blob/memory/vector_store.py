import chromadb
import logging
import os
from pathlib import Path
import uuid
import time
from blob.memory.decay import DecayAlgorithm

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, db_path: str):
        path = Path(db_path).expanduser()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        self.client = chromadb.PersistentClient(path=str(path))
        self.episodic = self.client.get_or_create_collection("episodic")
        self.semantic = self.client.get_or_create_collection("semantic")
        self.decay_algo = DecayAlgorithm()

    def _collection(self, name: str):
        if name == "episodic":
            return self.episodic
        if name == "semantic":
            return self.semantic
        raise ValueError(f"Unknown memory collection: {name}")

    def store(self, text: str, metadata: dict, collection: str = "episodic", memory_id: str | None = None):
        doc_id = memory_id or str(uuid.uuid4())
        now = time.time()
        values = dict(metadata)
        values.setdefault("timestamp", now)
        values.setdefault("last_accessed", now)
        values.setdefault("access_count", 0)
        self._collection(collection).upsert(documents=[text], metadatas=[values], ids=[doc_id])
        return doc_id
        
    def recall(self, query: str, top_k: int = 5, collection: str = "episodic") -> list:
        col = self._collection(collection)
        if not query.strip() or top_k <= 0 or col.count() == 0:
            return []
        results = col.query(query_texts=[query], n_results=min(top_k * 3, col.count()))
        candidates = []
        current_time = time.time()
        for doc, meta, id_, dist in zip(results['documents'][0], results['metadatas'][0], results['ids'][0], results['distances'][0]):
            meta = dict(meta or {})
            # Chroma's default L2 distance is not bounded by one.
            base_sim = 1.0 / (1.0 + max(0.0, dist))
            last_accessed = meta.get("last_accessed", current_time)
            days_since = max(0, current_time - last_accessed) / 86400
            score = self.decay_algo.calculate_score(base_sim, days_since, meta.get("access_count", 0), pinned=meta.get("pinned", False))
            candidates.append({"id": id_, "text": doc, "metadata": meta, "score": score})
        recalled = sorted(candidates, key=lambda item: item["score"], reverse=True)[:top_k]
        for item in recalled:
            meta = dict(item["metadata"])
            meta["last_accessed"] = current_time
            meta["access_count"] = meta.get("access_count", 0) + 1
            col.update(ids=[item["id"]], metadatas=[meta])
            item["metadata"] = meta
        return recalled

    def unconsolidated_episodes(self, limit: int = 20) -> list:
        data = self.episodic.get(where={"consolidated": {"$ne": True}}, limit=limit, include=["documents", "metadatas"])
        return [{"id": id_, "text": text, "metadata": metadata} for id_, text, metadata in zip(data["ids"], data["documents"], data["metadatas"])]

    def mark_consolidated(self, episodes: list):
        for episode in episodes:
            metadata = dict(episode["metadata"] or {})
            metadata["consolidated"] = True
            self.episodic.update(ids=[episode["id"]], metadatas=[metadata])

    def delete(self, memory_id: str, collection: str = "episodic"):
        self._collection(collection).delete(ids=[memory_id])
