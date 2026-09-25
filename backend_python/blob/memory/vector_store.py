import chromadb
import asyncio
import logging
from blob.memory.decay import DecayAlgorithm

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, db_path: str):
        self.client = chromadb.PersistentClient(path=db_path)
        self.episodic = self.client.get_or_create_collection("episodic")
        self.semantic = self.client.get_or_create_collection("semantic")
        self.decay_algo = DecayAlgorithm()
        self.memory_id_counter = 0

    def store(self, text: str, metadata: dict):
        self.memory_id_counter += 1
        doc_id = str(self.memory_id_counter)
        self.episodic.add(documents=[text], metadatas=[metadata], ids=[doc_id])
        
    def recall(self, query: str, top_k: int = 5) -> list:
        results = self.episodic.query(query_texts=[query], n_results=top_k)
        if not results['documents']:
            return []
        
        recalled = []
        for doc, meta, id_ in zip(results['documents'][0], results['metadatas'][0], results['ids'][0]):
            recalled.append({"id": id_, "text": doc, "metadata": meta})
        return recalled

    def delete(self, memory_id: str):
        self.episodic.delete(ids=[memory_id])

    async def consolidation_loop(self):
        while True:
            await asyncio.sleep(3600)  # every hour
            logger.info("Consolidating memories...")
