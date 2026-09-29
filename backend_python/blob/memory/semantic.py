import asyncio
import hashlib
import logging
import re
import time

logger = logging.getLogger(__name__)
TEMPORARY_FACT = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|right now|this (?:morning|afternoon|evening|week|month|year))\b"
    r"|\b(?:next|last|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|week|month|year)\b"
    r"|\bin\s+\d+\s+(?:minutes?|hours?|days?|weeks?|months?)\b"
    r"|\b(?:it(?:'s| is)|the day is)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def is_temporary_fact(text: str) -> bool:
    """Keep relative-time statements out of long-term facts and prompt context."""
    return bool(TEMPORARY_FACT.search(text))


def _sentence_key(text: str) -> str:
    return " ".join(text.strip().strip("\"'` ").rstrip(".!? ").casefold().split())


def _user_sentences(messages: list[str]) -> dict[str, str]:
    """Return exact user sentences eligible for durable memory."""
    sentences = {}
    for message in messages:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", message):
            sentence = sentence.strip()
            key = _sentence_key(sentence)
            if key and len(sentence) <= 400 and not is_temporary_fact(sentence):
                sentences.setdefault(key, sentence)
    return sentences


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
        source_sentences = list(_user_sentences(user_messages).values())
        if not source_sentences:
            return True
        prompt = (
            "Each numbered line is a sentence the user actually said. Select lines that "
            "state durable facts about the user, such as preferences, names, habits, or "
            "ongoing projects. Keep qualifiers and negations. Ignore temporary facts about "
            "today, tomorrow, weather, or time. Return only the selected line numbers "
            "separated by commas, or exactly NONE. No explanation.\n\n"
            + "\n".join(f"{number}. {sentence}" for number, sentence in enumerate(source_sentences, 1))
        )
        try:
            msg = await self.llm.generate(prompt, "", "You extract factual user memories.")
            summary = (msg.content or "").strip()
            if summary.upper() == "NONE":
                return True
            if not re.fullmatch(r"\d+(?:\s*[,\n]\s*\d+)*", summary):
                logger.debug("Rejected malformed memory selection")
                return True
            seen = set()
            for number_text in re.findall(r"\d+", summary):
                number = int(number_text)
                if 1 <= number <= len(source_sentences):
                    source = source_sentences[number - 1]
                    normalized = _sentence_key(source)
                    memory_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    if memory_id in seen:
                        continue
                    seen.add(memory_id)
                    self.vector_store.store(
                        source,
                        {"type": "semantic", "timestamp": time.time(), "pinned": True,
                         "grounded": True},
                        collection="semantic", memory_id=memory_id, skip_existing=True,
                    )
            return True
        except Exception:
            logger.exception("Failed to consolidate user memories")
            return False

    def recall_facts(self, query: str, top_k: int = 5,
                     max_distance: float | None = None) -> list:
        return self.vector_store.recall(query, top_k=top_k, collection="semantic",
                                        max_distance=max_distance)

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
