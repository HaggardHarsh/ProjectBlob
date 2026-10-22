import asyncio
import hashlib
import logging
import re
import time
from blob.memory.lifecycle import ACADEMIC_TOPICS, PROFILE_TOPICS, MIDDLE_LIFETIME_DAYS, middle_expiry, topic_key

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
        for sentence in re.split(r"(?<=[.!?])\s+|\n+|,\s+(?=I\s+(?:have|am|will|need|want)\b)", message):
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

    def remember_explicit_statements(self, message: str, source_episode_id=None, source_timestamp=None):
        """Save explicit selectors and naming preferences without model consolidation."""
        timestamp = time.time() if source_timestamp is None else source_timestamp
        for sentence in _user_sentences([message], include_temporary=True).values():
            topic = topic_key(sentence)
            if (topic not in ACADEMIC_TOPICS + PROFILE_TOPICS or sentence.endswith("?") or
                    (topic in PROFILE_TOPICS and is_temporary_fact(sentence))):
                continue
            tier = "semantic" if topic in PROFILE_TOPICS else "middle"
            metadata = {"type": tier, "tier": "long" if tier == "semantic" else "middle",
                        "timestamp": timestamp, "source_timestamp": timestamp,
                        "pinned": tier == "semantic", "grounded": True, "topic_key": topic}
            if tier == "middle":
                metadata["expires_at"] = timestamp + MIDDLE_LIFETIME_DAYS * 86400
            if isinstance(source_episode_id, str):
                metadata["source_episode_id"] = source_episode_id
            memory_id = hashlib.sha256(_sentence_key(sentence).encode()).hexdigest()
            self.vector_store.store_grounded(sentence, metadata, tier, memory_id)

    def profile_context(self) -> str:
        """Keep current naming evidence available even for an ambiguous follow-up."""
        facts = self.vector_store.list_active("semantic", topic_keys=PROFILE_TOPICS)
        return "\n".join(
            "Current naming preference (exact user statement, evidence only): " + item["text"]
            for item in facts
            if (item.get("metadata") or {}).get("grounded") is True
            and not is_temporary_fact(item["text"]))

    def document_context(self, query: str, *, max_bytes=1400) -> str:
        """Give file analysis exact user quotes, with current academic selectors first."""
        selectors = []
        for tier in ("middle", "semantic"):
            selectors.extend(self.vector_store.list_active(tier, limit=4, topic_keys=ACADEMIC_TOPICS + PROFILE_TOPICS))
        selectors = [item for item in selectors if (item.get("metadata") or {}).get("grounded") is True]
        selectors.sort(key=lambda item: (item.get("metadata") or {}).get("source_timestamp", 0), reverse=True)
        # Metadata lookup ensures an exam question retrieves subjects even when
        # their vocabulary is distant from "Monday" in embedding space.
        selected_topics = {item["metadata"].get("topic_key") for item in selectors}
        facts = self.recall_middle(query, top_k=3, max_distance=1.35) + self.recall_facts(query, top_k=3, max_distance=1.35)
        candidates = [("Current user statement", item["text"]) for item in selectors]
        for item in facts:
            meta = item.get("metadata") or {}
            if (meta.get("grounded") is True and meta.get("topic_key") not in selected_topics and
                    topic_key(item["text"]) not in ACADEMIC_TOPICS):
                candidates.append(("Saved user statement", item["text"]))
        episodes = self.vector_store.recall(query, top_k=3, collection="episodic", max_distance=1.35,
                                            min_timestamp=time.time() - 7 * 86400)
        for episode in episodes:
            text = episode["text"]
            if not text.startswith("User: "):
                continue
            user = text.partition("\nBlob: ")[0].removeprefix("User: ")
            for sentence in _user_sentences([user], include_temporary=True).values():
                if (sentence.endswith("?") or re.match(
                        r"^(?:who|what|when|where|why|how|which|can|could|would|do|does|did|is|are|will)\b", sentence, re.I)):
                    continue
                if topic_key(sentence) not in selected_topics and topic_key(sentence) not in ACADEMIC_TOPICS:
                    candidates.append(("Earlier user statement", sentence))
        lines, seen, used = [], set(), 0
        for label, quote in candidates:
            key = _sentence_key(quote)
            if key in seen:
                continue
            seen.add(key)
            line = f"{label}: {quote}"
            size = len(line.encode("utf-8")) + 1
            if used + size <= max_bytes:
                lines.append(line)
                used += size
        return "\n".join(lines)

    def backfill_explicit_statements(self):
        """Recover clear declarations from preexisting user-authored episode archives."""
        controls = getattr(self.vector_store, "controls", None)
        if controls and controls.paused:
            return
        data = self.vector_store.episodic.get(include=["documents", "metadatas"])
        newest = {}
        for episode_id, text, metadata in zip(data["ids"], data["documents"], data["metadatas"]):
            if not text.startswith("User: "):
                continue
            timestamp = (metadata or {}).get("timestamp", 0)
            if not timestamp:
                continue
            for sentence in _user_sentences([text.partition("\nBlob: ")[0][6:]], include_temporary=True).values():
                topic = topic_key(sentence)
                if (topic in ACADEMIC_TOPICS + PROFILE_TOPICS and not sentence.endswith("?") and
                        not (topic in PROFILE_TOPICS and is_temporary_fact(sentence)) and
                        (topic not in newest or timestamp >= newest[topic][0])):
                    newest[topic] = (timestamp, sentence, episode_id)
        for timestamp, sentence, episode_id in newest.values():
            memory_id = hashlib.sha256(_sentence_key(sentence).encode()).hexdigest()
            collection = self.vector_store.semantic if topic_key(sentence) in PROFILE_TOPICS else self.vector_store.middle
            existing = collection.get(ids=[memory_id], include=["metadatas"])
            if existing["ids"] and (existing["metadatas"][0] or {}).get("source_timestamp", 0) >= timestamp:
                continue
            self.remember_explicit_statements(sentence, episode_id, timestamp)

    async def summarize_and_store(self, episodes: list) -> bool:
        controls = getattr(self.llm, "controls", None)
        if controls and (controls.paused or not controls.cloud_enabled):
            return False
        deletion_revision = getattr(self.vector_store, "deletion_revision", 0)
        privacy_generation = controls.generation if controls else None
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
            "Each numbered line is an exact user statement. Select only factual user statements worth remembering. "
            "Use L for lasting facts (name, hobbies, favorites, stable preferences). "
            "Use M for active projects or future events (exams, appointments, deadlines) that should expire. "
            "Never use L for a dated or relative-time statement. Ignore simple date/time/weather claims, "
            "past one-off events, and questions that reveal no fact. Keep negations and qualifiers. "
            "Return only codes like L1,M2, or exactly NONE. No explanation.\n\n"
            + "\n".join(f"{number}. {sentence}" for number, (sentence, _) in enumerate(source_sentences, 1))
        )
        try:
            msg = await self.llm.generate(prompt, "", "You extract factual user memories.")
            if (getattr(self.vector_store, "deletion_revision", 0) != deletion_revision or
                    (controls and (controls.generation != privacy_generation or controls.paused))):
                return False
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
                    topic = topic_key(source)
                    if topic in ACADEMIC_TOPICS:
                        tier = "middle"
                    elif topic in PROFILE_TOPICS and not is_temporary_fact(source):
                        # Background selection must not demote a durable naming
                        # instruction that was already saved immediately.
                        tier = "semantic"
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
                    model = getattr(self.llm, "model_name", None)
                    if isinstance(model, str):
                        metadata["consolidation_model"] = model
                    if episode.get("id"):
                        metadata["source_episode_id"] = episode["id"]
                    if topic:
                        metadata["topic_key"] = topic
                    if tier == "middle":
                        metadata["expires_at"] = (source_timestamp + MIDDLE_LIFETIME_DAYS * 86400 if topic in ACADEMIC_TOPICS
                                                  else middle_expiry(source, source_timestamp))
                    self.vector_store.store_grounded(source, metadata, tier, memory_id)
            return True
        except asyncio.CancelledError:
            # Privacy cancellation of the provider request must not kill this periodic worker.
            if asyncio.current_task().cancelling():
                raise
            return False
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

    def list_facts(self, limit: int = 12) -> list:
        return self.vector_store.list_active("semantic", limit=limit)

    def list_middle(self, limit: int = 8) -> list:
        return self.vector_store.list_active("middle", limit=limit)

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
