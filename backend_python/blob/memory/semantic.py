import asyncio
import hashlib
import logging
import re
import time

logger = logging.getLogger(__name__)
TEMPORARY_FACT = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|right now|this (?:morning|afternoon|evening|week|month|year))\b"
    r"|\b(?:it(?:'s| is)|the day is)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def is_temporary_fact(text: str) -> bool:
    """Keep relative-time statements out of long-term facts and prompt context."""
    return bool(TEMPORARY_FACT.search(text))


class SemanticMemory:
    def __init__(self, vector_store, llm_engine):
        self.vector_store = vector_store
        self.llm = llm_engine

    async def summarize_and_store(self, episodes: list) -> bool:
        if not episodes:
            return True
        # The assistant's previous output is not evidence about the user.
        user_messages = []
        seen_messages = set()
        for episode in episodes:
            text = episode["text"]
            if text.startswith("User: "):
                message = text.split("\nBlob: ", 1)[0][6:]
                key = " ".join(message.casefold().split())
                if key not in seen_messages:
                    seen_messages.add(key)
                    user_messages.append(message)
        if not user_messages:
            return True
        prompt = (
            "Extract only durable facts explicitly stated by the user below, such as "
            "preferences (especially how Blob should speak to them or how familiar it should be) "
            "or ongoing projects. Do not infer facts from assistant replies. "
            "Do not store temporary facts about today, tomorrow, the current weekday, weather, or time. "
            "Return one short fact per line, or exactly NONE. No numbering.\n\n"
            + "\n".join(f"User: {message}" for message in user_messages)
        )
        try:
            msg = await self.llm.generate(prompt, "", "You extract factual user memories.")
            summary = (msg.content or "").strip()
            seen = set()
            if summary.rstrip(" .!").upper() != "NONE":
                for line in summary.splitlines():
                    fact = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
                    if not fact or fact.rstrip(" .!").upper() == "NONE" or is_temporary_fact(fact):
                        continue
                    normalized = " ".join(fact.casefold().split())
                    memory_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    if memory_id in seen:
                        continue
                    seen.add(memory_id)
                    self.vector_store.store(
                        fact,
                        {"type": "semantic", "timestamp": time.time(), "pinned": True},
                        collection="semantic", memory_id=memory_id, skip_existing=True,
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
