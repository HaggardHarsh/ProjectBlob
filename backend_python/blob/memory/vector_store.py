import chromadb
import logging
import math
from contextlib import nullcontext
import os
from pathlib import Path
import uuid
import time
import threading
from blob.memory.decay import DecayAlgorithm
from blob.memory.lifecycle import is_active, topic_key

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, db_path: str, *, embedding_function=None, controls=None):
        self.controls = controls
        self.deletion_revision = 0
        path = Path(db_path).expanduser()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        self.client = chromadb.PersistentClient(path=str(path))
        embedding_options = {"embedding_function": embedding_function} if embedding_function is not None else {}
        self.episodic = self.client.get_or_create_collection("episodic", **embedding_options)
        # Search user words separately so an invented assistant reply cannot
        # make an unrelated conversation look like a relevant user memory.
        self.episodic_user = self.client.get_or_create_collection("episodic_user", **embedding_options)
        self.semantic = self.client.get_or_create_collection("semantic", **embedding_options)
        self.middle = self.client.get_or_create_collection("middle", **embedding_options)
        self.decay_algo = DecayAlgorithm()
        self._write_lock = threading.RLock()
        self.semantic_revision = 0
        self._backfill_episode_index()

    @staticmethod
    def _episode_user_text(document: str) -> str:
        if document.startswith("User: "):
            return document.split("\nBlob: ", 1)[0][6:] or "[Empty user message]"
        return "[Unattributed archived episode]"

    def _backfill_episode_index(self) -> int:
        """Reconcile the search index with archived episodes after a restart."""
        episode_ids = set(self.episodic.get(include=[])["ids"])
        indexed_ids = set(self.episodic_user.get(include=[])["ids"])
        stale = list(indexed_ids - episode_ids)
        for start in range(0, len(stale), 100):
            self.episodic_user.delete(ids=stale[start:start + 100])
        missing_ids = list(episode_ids - indexed_ids)
        for start in range(0, len(missing_ids), 100):
            data = self.episodic.get(ids=missing_ids[start:start + 100],
                                     include=["documents", "metadatas"])
            self.episodic_user.upsert(
                ids=data["ids"],
                documents=[self._episode_user_text(document) for document in data["documents"]],
                metadatas=[{"timestamp": (meta or {}).get("timestamp", 0.0)}
                           for meta in data["metadatas"]],
            )
        if missing_ids or stale:
            logger.info("Reconciled memory search index: %d added, %d removed",
                        len(missing_ids), len(stale))
        return len(missing_ids)

    def backfill_grounded_provenance(self) -> int:
        """Attach source and correction topics to older verbatim long-term facts."""
        facts = self.semantic.get(include=["documents", "metadatas"])
        missing = [(item_id, text, dict(meta or {})) for item_id, text, meta in
                   zip(facts["ids"], facts["documents"], facts["metadatas"])
                   if (meta or {}).get("grounded") is True and not (meta or {}).get("source_episode_id")]
        if not missing:
            return 0
        episodes = self.episodic.get(include=["documents", "metadatas"])
        sources = []
        for item_id, document, meta in zip(episodes["ids"], episodes["documents"], episodes["metadatas"]):
            if document.startswith("User: "):
                sources.append((item_id, document.split("\nBlob: ", 1)[0][6:],
                                (meta or {}).get("timestamp", 0)))
        updated = 0
        for item_id, text, meta in missing:
            matches = [(source_id, timestamp) for source_id, user, timestamp in sources if text in user]
            if not matches:
                continue
            source_id, timestamp = max(matches, key=lambda item: item[1])
            meta.update({"source_episode_id": source_id, "source_timestamp": timestamp,
                         "tier": "long"})
            key = topic_key(text)
            if key:
                meta["topic_key"] = key
            self.semantic.update(ids=[item_id], metadatas=[meta])
            updated += 1
        if updated:
            self.semantic_revision += 1
        return updated

    def _collection(self, name: str):
        if name == "episodic":
            return self.episodic
        if name == "semantic":
            return self.semantic
        if name == "middle":
            return self.middle
        raise ValueError(f"Unknown memory collection: {name}")

    def store(self, text: str, metadata: dict, collection: str = "episodic", memory_id: str | None = None,
              skip_existing: bool = False):
        controls = getattr(self, "controls", None)
        with controls.writing() if controls else nullcontext():
            return self._store(text, metadata, collection, memory_id, skip_existing)

    def _store(self, text, metadata, collection, memory_id, skip_existing):
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
        if collection == "episodic" and hasattr(self, "episodic_user"):
            self.episodic_user.upsert(
                documents=[self._episode_user_text(text)],
                metadatas=[{"timestamp": values["timestamp"]}], ids=[doc_id],
            )
        if collection in {"semantic", "middle"}:
            self.semantic_revision = getattr(self, "semantic_revision", 0) + 1
        return doc_id

    def complete_episode(self, memory_id: str, reply: str) -> bool:
        """Update only an existing source; a forgotten episode must never be recreated."""
        controls = getattr(self, "controls", None)
        with controls.writing() if controls else nullcontext():
            with self._write_lock:
                data = self.episodic.get(ids=[memory_id], include=["documents", "metadatas"])
                if not data["ids"]:
                    return False
                metadata = dict(data["metadatas"][0] or {})
                document = data["documents"][0]
                user = document if metadata.get("user_only") else document.partition("\nBlob: ")[0]
                metadata["user_only"] = False
                # Only the reply changes. Preserve source time and consolidation
                # state so an in-flight reply cannot redate or reselect user facts.
                self._store(user + "\nBlob: " + reply, metadata, "episodic", memory_id, False)
                return True

    def store_grounded(self, text: str, metadata: dict, collection: str, memory_id: str):
        """Store an exact user quote and supersede older facts on the same clear topic."""
        controls = getattr(self, "controls", None)
        with controls.writing() if controls else nullcontext():
            with getattr(self, "_write_lock", nullcontext()):
                return self._store_grounded(text, metadata, collection, memory_id)

    def _store_grounded(self, text: str, metadata: dict, collection: str, memory_id: str):
        if collection not in {"semantic", "middle"}:
            raise ValueError("Grounded memories must be long or middle term")
        values = dict(metadata)
        # Chroma upsert can retain old metadata keys, so clear a previous
        # supersession when the same sentence is newly reasserted.
        values["superseded_by"] = ""
        topic = values.get("topic_key")
        source_time = values["source_timestamp"]
        existing = []
        if topic:
            for name in ("semantic", "middle"):
                data = self._collection(name).get(where={"topic_key": topic}, include=["metadatas"])
                existing.extend((name, item_id, dict(meta or {})) for item_id, meta in
                                zip(data["ids"], data["metadatas"]))
        current = self._collection(collection).get(ids=[memory_id], include=["metadatas"])
        if current["ids"]:
            old_meta = current["metadatas"][0] or {}
            if old_meta.get("source_timestamp", 0) > source_time:
                return memory_id
        newer = [(item_id, meta) for name, item_id, meta in existing
                 if (name, item_id) != (collection, memory_id)
                 and is_active(meta) and meta.get("source_timestamp", meta.get("timestamp", 0)) > source_time]
        if newer:
            values["superseded_by"] = max(newer, key=lambda item: item[1].get("source_timestamp", 0))[0]
        self.store(text, values, collection=collection, memory_id=memory_id)
        if topic and not newer:
            for name, item_id, meta in existing:
                if (name, item_id) == (collection, memory_id) or not is_active(meta):
                    continue
                if meta.get("source_timestamp", meta.get("timestamp", 0)) <= source_time:
                    meta["superseded_by"] = memory_id
                    self._collection(name).update(ids=[item_id], metadatas=[meta])
                    self.semantic_revision += 1
        return memory_id
        
    def recall(self, query: str, top_k: int = 5, collection: str = "episodic",
               max_distance: float | None = None, min_timestamp: float | None = None,
               search_full_episode: bool = False) -> list:
        col = self._collection(collection)
        search_col = (self.episodic_user if collection == "episodic" and
                      not search_full_episode and hasattr(self, "episodic_user") else col)
        if not query.strip() or top_k <= 0 or search_col.count() == 0:
            return []
        current_time = time.time()
        where = None
        if collection == "middle":
            where = {"expires_at": {"$gt": current_time}}
        elif collection == "episodic" and min_timestamp is not None:
            where = {"timestamp": {"$gte": min_timestamp}}
        query_args = {"query_texts": [query], "n_results": min(top_k * 10, search_col.count())}
        if where is not None:
            query_args["where"] = where
        results = search_col.query(**query_args)
        originals = {}
        if search_col is not col and results["ids"][0]:
            data = col.get(ids=results["ids"][0], include=["documents", "metadatas"])
            originals = {item_id: (doc, meta) for item_id, doc, meta in
                         zip(data["ids"], data["documents"], data["metadatas"])}
        candidates = []
        for doc, meta, id_, dist in zip(results['documents'][0], results['metadatas'][0], results['ids'][0], results['distances'][0]):
            if search_col is not col:
                if id_ not in originals:
                    continue
                doc, meta = originals[id_]
            # A nearest neighbour is not necessarily a relevant memory. Gate on
            # the raw embedding distance before recency or access can affect rank.
            if not math.isfinite(dist) or (max_distance is not None and dist > max_distance):
                continue
            meta = dict(meta or {})
            if not is_active(meta, current_time):
                continue
            if min_timestamp is not None and meta.get("timestamp", 0) < min_timestamp:
                continue
            # Chroma's default L2 distance is not bounded by one.
            base_sim = 1.0 / (1.0 + max(0.0, dist))
            created_at = meta.get("timestamp", current_time)
            days_since = max(0, current_time - created_at) / 86400
            score = self.decay_algo.calculate_score(base_sim, days_since, 0, pinned=meta.get("pinned", False))
            candidates.append({"id": id_, "text": doc, "metadata": meta, "score": score})
        recalled = sorted(candidates, key=lambda item: item["score"], reverse=True)[:top_k]
        return recalled

    def purge_expired_middle(self, now: float | None = None) -> int:
        current = time.time() if now is None else now
        expired = self.middle.get(where={"expires_at": {"$lte": current}}, include=[])["ids"]
        if expired:
            self.middle.delete(ids=expired)
            self.semantic_revision += 1
        return len(expired)

    def list_active(self, collection: str, limit: int = 20, topic_keys: tuple[str, ...] | None = None) -> list:
        """List current facts for broad questions that have no useful search terms."""
        if collection not in {"semantic", "middle"} or limit <= 0:
            return []
        filters = {"where": {"topic_key": {"$in": list(topic_keys)}}} if topic_keys else {}
        data = self._collection(collection).get(include=["documents", "metadatas"], **filters)
        current_time = time.time()
        items = [
            {"id": item_id, "text": doc, "metadata": dict(meta or {})}
            for item_id, doc, meta in zip(data["ids"], data["documents"], data["metadatas"])
            if is_active(meta, current_time)
        ]
        items.sort(key=lambda item: item["metadata"].get(
            "source_timestamp", item["metadata"].get("timestamp", 0)), reverse=True)
        return items[:limit]

    def unconsolidated_episodes(self, limit: int = 20) -> list:
        data = self.episodic.get(where={"consolidated": {"$ne": True}}, limit=limit, include=["documents", "metadatas"])
        return [{"id": id_, "text": text, "metadata": metadata} for id_, text, metadata in zip(data["ids"], data["documents"], data["metadatas"])]

    def mark_consolidated(self, episodes: list):
        controls = getattr(self, "controls", None)
        with controls.writing() if controls else nullcontext():
            with getattr(self, "_write_lock", nullcontext()):
                # A reply may have completed while consolidation awaited its
                # model. Merge current metadata instead of restoring the snapshot.
                data = self.episodic.get(ids=[episode["id"] for episode in episodes], include=["metadatas"])
                for memory_id, metadata in zip(data["ids"], data["metadatas"]):
                    values = dict(metadata or {})
                    values["consolidated"] = True
                    self.episodic.update(ids=[memory_id], metadatas=[values])

    def delete(self, memory_id: str, collection: str = "episodic"):
        self._collection(collection).delete(ids=[memory_id])
        if collection == "episodic" and hasattr(self, "episodic_user"):
            self.episodic_user.delete(ids=[memory_id])
        if collection in {"semantic", "middle"}:
            self.semantic_revision = getattr(self, "semantic_revision", 0) + 1

    def forget_personal_memory(self, tier=None, memory_id=None):
        """Remove source episodes as well, so consolidation cannot restore deleted facts."""
        with self._write_lock:
            self.deletion_revision += 1
            if tier is None:
                total = 0
                for name in ("episodic", "middle", "semantic"):
                    ids = self._collection(name).get(include=[])["ids"]
                    total += len(ids)
                    for start in range(0, len(ids), 100):
                        self._collection(name).delete(ids=ids[start:start + 100])
                indexed = self.episodic_user.get(include=[])["ids"]
                for start in range(0, len(indexed), 100):
                    self.episodic_user.delete(ids=indexed[start:start + 100])
                self.semantic_revision += 1
                return total
            record = self._collection(tier).get(ids=[memory_id], include=["metadatas", "documents"])
            if not record["ids"]:
                return 0
            episode_id = memory_id if tier == "episodic" else (record["metadatas"][0] or {}).get("source_episode_id")
            source_ids = {episode_id} if episode_id else set()
            if tier != "episodic":
                # A repeated declaration may have several archived sources.
                archives = self.episodic.get(include=["documents"])
                quote = record["documents"][0]
                source_ids.update(item_id for item_id, text in zip(archives["ids"], archives["documents"])
                                  if quote in self._episode_user_text(text))
            removed = {(tier, memory_id)}
            for episode_id in source_ids:
                if self.episodic.get(ids=[episode_id], include=[])["ids"]:
                    removed.add(("episodic", episode_id))
                for name in ("middle", "semantic"):
                    linked = self._collection(name).get(where={"source_episode_id": episode_id}, include=[])["ids"]
                    removed.update((name, item_id) for item_id in linked)
            for name, item_id in removed:
                self.delete(item_id, name)
            return len(removed)
