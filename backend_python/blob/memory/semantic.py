import asyncio
import hashlib
import logging
import re
import time

logger = logging.getLogger(__name__)


class SemanticMemory:
    def __init__(self, vector_store, llm_engine):
        self.vector_store = vector_store
        self.llm = llm_engine

    async def summarize_and_store(self, episodes: list) -> bool:
        if not episodes:
            return True
        # The assistant's previous output is not evidence about the user.
        user_messages = []
        for episode in episodes:
            text = episode["text"]
            if text.startswith("User: "):
                user_messages.append(text.split("\nBlob: ", 1)[0][6:])
        if not user_messages:
            return True
        prompt = (
            "Extract only durable facts explicitly stated by the user below, such as "
            "preferences (especially how Blob should speak to them or how familiar it should be) "
            "or ongoing projects. Do not infer facts from assistant replies. "
            "Return one short fact per line, or exactly NONE. No numbering.\n\n"
            + "\n".join(f"User: {message}" for message in user_messages)
        )
        try:
            msg = await self.llm.generate(prompt, "", "You extract factual user memories.")
            summary = (msg.content or "").strip()
            if summary.rstrip(" .!").upper() != "NONE":
                for line in summary.splitlines():
                    fact = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
                    if not fact or fact.rstrip(" .!").upper() == "NONE":
                        continue
                    normalized = " ".join(fact.casefold().split())
                    memory_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    self.vector_store.store(
                        fact,
                        {"type": "semantic", "timestamp": time.time(), "pinned": True},
                        collection="semantic", memory_id=memory_id,
                    )
            return True
        except Exception:
            logger.exception("Failed to consolidate user memories")
            return False

    def recall_facts(self, query: str, top_k: int = 5) -> list:
        return self.vector_store.recall(query, top_k=top_k, collection="semantic")

    async def consolidate_once(self) -> int:
        episodes = self.vector_store.unconsolidated_episodes(limit=20)
        if episodes and await self.summarize_and_store(episodes):
            self.vector_store.mark_consolidated(episodes)
            return len(episodes)
        return 0

    async def consolidation_loop(self):
        while True:
            try:
                await self.consolidate_once()
            except Exception:
                logger.exception("Memory consolidation failed")
            await asyncio.sleep(60)
