import asyncio
import hashlib
import logging
import re
import time
from blob.memory.lifecycle import middle_expiry, topic_key

logger = logging.getLogger(__name__)
TEMPORARY_FACT = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|right now|this (?:morning|afternoon|evening|week|month|year))\b"
    r"|\b(?:next|last|this)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|week|month|year)\b"
    r"|\bin\s+\d+\s+(?:minutes?|hours?|days?|weeks?|months?)\b"
    r"|\b(?:it(?:'s| is)|the day is)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


def is_temporary_fact(text: str) -> bool:
    """Keep relative-time statements out of long-term facts and prompt context."""
    return bool(TEMPORARY_FACT.search(text))


def _sentence_key(text: str) -> str:
    return " ".join(text.strip().strip("\"'` ").rstrip(".!? ").casefold().split())


def _user_sentences(messages: list[str], include_temporary: bool = False) -> dict[str, str]:
    """Return exact user sentences; temporary ones are eligible only for middle term."""
    sentences = {}
    for message in messages:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", message):
            sentence = sentence.strip()
            key = _sentence_key(sentence)
            trivial_clock = re.fullmatch(
                r"(?:(?:today(?:\s+is)?|it(?:'s| is)|the day is)\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)[.!?]?",
                sentence, re.IGNORECASE,
            )
            if key and len(sentence) <= 400 and not trivial_clock and (include_temporary or not is_temporary_fact(sentence)):
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
        sources = {}
        for episode in sorted(episodes, key=lambda item: (item.get("metadata") or {}).get("timestamp", 0)):
            text = episode["text"]
            if text.startswith("User: "):
                message = text.split("\nBlob: ", 1)[0][6:]
                for key, sentence in _user_sentences([message], include_temporary=True).items():
                    original = sources[key][0] if key in sources else sentence
                    sources[key] = (original, episode)
        source_sentences = list(sources.values())
        if not source_sentences:
            return True
        prompt = (
            "Each numbered line is an exact user sentence. Select only factual user statements worth remembering. "
            "Use L for lasting facts (name, hobbies, favorites, stable preferences). "
            "Use M for active projects or future events (exams, appointments, deadlines) that should expire. "
            "Never use L for a dated or relative-time statement. Ignore simple date/time/weather claims, "
            "past one-off events, and questions that reveal no fact. Keep negations and qualifiers. "
            "Return only codes like L1,M2, or exactly NONE. No explanation.\n\n"
            + "\n".join(f"{number}. {sentence}" for number, (sentence, _) in enumerate(source_sentences, 1))
        )
        try:
            msg = await self.llm.generate(prompt, "", "You extract factual user memories.")
            summary = (msg.content or "").strip()
            if summary.upper() == "NONE":
                return True
            if not re.fullmatch(r"[LM]?\d+(?:\s*[,\n]\s*[LM]?\d+)*", summary, re.IGNORECASE):
                logger.debug("Rejected malformed memory selection")
                return False
            seen = set()
            for token in re.split(r"\s*[,\n]\s*", summary):
                tier = "middle" if token[:1].upper() == "M" else "semantic"
                number = int(token.lstrip("LlMm"))
                if 1 <= number <= len(source_sentences):
                    source, episode = source_sentences[number - 1]
                    if tier == "semantic" and is_temporary_fact(source):
                        continue
                    normalized = _sentence_key(source)
                    memory_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    if (tier, memory_id) in seen:
                        continue
                    seen.add((tier, memory_id))
                    source_timestamp = (episode.get("metadata") or {}).get("timestamp", time.time())
                    metadata = {"type": tier, "tier": "long" if tier == "semantic" else "middle",
                                "timestamp": source_timestamp, "source_timestamp": source_timestamp,
                                "pinned": tier == "semantic", "grounded": True}
                    if episode.get("id"):
                        metadata["source_episode_id"] = episode["id"]
                    topic = topic_key(source)
                    if topic:
                        metadata["topic_key"] = topic
                    if tier == "middle":
                        metadata["expires_at"] = middle_expiry(source, source_timestamp)
                    self.vector_store.store_grounded(source, metadata, tier, memory_id)
            return True
        except Exception:
            logger.exception("Failed to consolidate user memories")
            return False

    def recall_facts(self, query: str, top_k: int = 5,
                     max_distance: float | None = None) -> list:
        return self.vector_store.recall(query, top_k=top_k, collection="semantic",
                                        max_distance=max_distance)

    def recall_middle(self, query: str, top_k: int = 5,
                      max_distance: float | None = None) -> list:
        return self.vector_store.recall(query, top_k=top_k, collection="middle",
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
                self.vector_store.purge_expired_middle()
                await self.consolidate_once()
            except Exception:
                logger.exception("Memory consolidation failed")
            await asyncio.sleep(60)
