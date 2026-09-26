import logging
import time

logger = logging.getLogger(__name__)

class SemanticMemory:
    def __init__(self, vector_store, llm_engine):
        self.vector_store = vector_store
        self.llm = llm_engine
        
    async def summarize_and_store(self, episodes: list):
        if not episodes:
            return
            
        # Combine episodes into a narrative
        text_block = "\n".join([ep['text'] for ep in episodes])
        
        prompt = (
            "Based on the following recent interactions between a User and Blob, "
            "extract any new, persistent facts about the user (e.g., name, preferences, job, projects, OS). "
            "Return ONLY the extracted facts, one per line. If there are no new persistent facts, return exactly 'NONE'.\n\n"
            f"{text_block}"
        )
        
        try:
            msg = await self.llm.generate(prompt, "", "You are a factual summarization engine.")
            summary = msg.content.strip()
            
            if summary and summary.upper() != "NONE":
                for fact in summary.split("\n"):
                    fact = fact.strip()
                    if fact:
                        self.vector_store.store(
                            fact,
                            {"type": "semantic", "timestamp": time.time()},
                            collection="semantic"
                        )
                        logger.info(f"Learned new semantic fact: {fact}")
                        
        except Exception as e:
            logger.error(f"Failed to summarize semantic facts: {e}")

    def recall_facts(self, query: str, top_k: int = 5) -> list:
        return self.vector_store.recall(query, top_k=top_k, collection="semantic")
        
    async def consolidation_loop(self):
        """Periodically scans recent episodes and consolidates them into semantic facts."""
        import asyncio
        while True:
            await asyncio.sleep(3600)  # Run every hour
            logger.info("Running memory consolidation...")
            
            # Fetch recent episodes (in a real app we'd track which ones are unprocessed)
            # For now, let's just grab the last 20 by using a blank query 
            # (or we could expose a get_recent() on episodic, but let's just query metadata)
            
            # Let's use a dummy query since chroma needs a query text
            results = self.vector_store.episodic.query(query_texts=["*"], n_results=20)
            if results and results['documents'] and results['documents'][0]:
                episodes = [{"text": doc} for doc in results['documents'][0]]
                await self.summarize_and_store(episodes)
