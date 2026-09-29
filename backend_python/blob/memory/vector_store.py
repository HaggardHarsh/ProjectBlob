import chromadb
import logging
import math
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
        self.semantic_revision = 0

    def _collection(self, name: str):
        if name == "episodic":
            return self.episodic
        if name == "semantic":
            return self.semantic
        raise ValueError(f"Unknown memory collection: {name}")

    def store(self, text: str, metadata: dict, collection: str = "episodic", memory_id: str | None = None,
              skip_existing: bool = False):
        doc_id = memory_id or str(uuid.uuid4())
        col = self._collection(collection)
        if skip_existing and col.get(ids=[doc_id], include=[])["ids"]:
            return doc_id
        now = time.time()
        values = dict(metadata)
        values.setdefault("timestamp", now)
        values.setdefault("last_accessed", now)
        values.setdefault("access_count", 0)
        col.upsert(documents=[text], metadatas=[values], ids=[doc_id])
        if collection == "semantic":
            self.semantic_revision = getattr(self, "semantic_revision", 0) + 1
        return doc_id
        
    def recall(self, query: str, top_k: int = 5, collection: str = "episodic",
               max_distance: float | None = None) -> list:
        col = self._collection(collection)
        if not query.strip() or top_k <= 0 or col.count() == 0:
            return []
        results = col.query(query_texts=[query], n_results=min(top_k * 3, col.count()))
        candidates = []
        current_time = time.time()
        for doc, meta, id_, dist in zip(results['documents'][0], results['metadatas'][0], results['ids'][0], results['distances'][0]):
            # A nearest neighbour is not necessarily a relevant memory. Gate on
            # the raw embedding distance before recency or access can affect rank.
            if not math.isfinite(dist) or (max_distance is not None and dist > max_distance):
                continue
            meta = dict(meta or {})
            # Chroma's default L2 distance is not bounded by one.
            base_sim = 1.0 / (1.0 + max(0.0, dist))
            created_at = meta.get("timestamp", current_time)
            days_since = max(0, current_time - created_at) / 86400
            score = self.decay_algo.calculate_score(base_sim, days_since, 0, pinned=meta.get("pinned", False))
            candidates.append({"id": id_, "text": doc, "metadata": meta, "score": score})
        recalled = sorted(candidates, key=lambda item: item["score"], reverse=True)[:top_k]
        updated_metadatas = []
        for item in recalled:
            meta = dict(item["metadata"])
            meta["last_accessed"] = current_time
            meta["access_count"] = meta.get("access_count", 0) + 1
            updated_metadatas.append(meta)
            item["metadata"] = meta
        if recalled:
            col.update(ids=[item["id"] for item in recalled], metadatas=updated_metadatas)
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
        if collection == "semantic":
            self.semantic_revision = getattr(self, "semantic_revision", 0) + 1
