from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest

from blob.memory.lifecycle import MIDDLE_LIFETIME_DAYS, middle_expiry, topic_key
from blob.memory.semantic import SemanticMemory, _user_sentences
from blob.memory.vector_store import VectorStore


def test_event_expiry_and_correction_topics():
    tuesday = datetime(2026, 9, 29, 12, tzinfo=timezone.utc).timestamp()
    tomorrow = middle_expiry("I have an exam tomorrow.", tuesday)
    next_wednesday = middle_expiry("I have an exam next Wednesday.", tuesday)
    assert 86400 < tomorrow - tuesday < 2 * 86400
    assert 7 * 86400 < next_wednesday - tuesday < 9 * 86400
    assert middle_expiry("I am building a model railway.", tuesday) == tuesday + MIDDLE_LIFETIME_DAYS * 86400
    assert topic_key("My favourite anime is Trigun.") == topic_key("Actually, my favorite anime is Frieren now.")
    assert topic_key("I love chess") == topic_key("I no longer like chess")
    assert topic_key("My hobbies are drawing and hiking") == topic_key("My hobby is painting")
    clauses = _user_sentences(
        ["I have an exam on Wednesday, I have a project due next month."],
        include_temporary=True,
    )
    assert list(clauses.values()) == ["I have an exam on Wednesday", "I have a project due next month."]


def test_existing_grounded_fact_gains_provenance_and_can_be_corrected(tmp_path):
    path = tmp_path / "memory"
    store = VectorStore(str(path))
    source_id = store.store("User: My favorite color is blue.\nBlob: Cool.",
                            {"type": "episodic", "timestamp": 1000.0})
    old_id = store.store("My favorite color is blue.",
                         {"type": "semantic", "grounded": True, "pinned": True},
                         collection="semantic")
    del store
    reopened = VectorStore(str(path))
    assert reopened.backfill_grounded_provenance() == 1
    old_meta = reopened.semantic.get(ids=[old_id], include=["metadatas"])["metadatas"][0]
    assert old_meta["source_episode_id"] == source_id
    assert old_meta["source_timestamp"] == 1000.0
    assert old_meta["topic_key"] == "favorite:color"
    reopened.store_grounded("My favorite color is green.",
                            {"type": "semantic", "tier": "long", "grounded": True,
                             "pinned": True, "source_timestamp": 2000.0,
                             "topic_key": "favorite:color"},
                            "semantic", "new-color")
    assert [item["text"] for item in reopened.recall("favorite color", collection="semantic")] == [
        "My favorite color is green."]


@pytest.mark.asyncio
async def test_middle_expires_and_new_long_term_fact_supersedes_old(tmp_path):
    store = VectorStore(str(tmp_path / "memory"))
    now = time.time()
    old = {"id": "episode-old", "text": "User: My favorite food is tofu.\nBlob: Nice.",
           "metadata": {"timestamp": now - 3600}}
    new = {"id": "episode-new", "text": "User: Actually, my favorite food is pasta now.\nBlob: Okay.",
           "metadata": {"timestamp": now}}
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="L1,L2")))
    memory = SemanticMemory(store, llm)

    assert await memory.summarize_and_store([old, new])
    saved = store.semantic.get(include=["documents", "metadatas"])
    by_text = dict(zip(saved["documents"], saved["metadatas"]))
    assert by_text["My favorite food is tofu."]["superseded_by"]
    assert by_text["Actually, my favorite food is pasta now."]["source_episode_id"] == "episode-new"
    assert [item["text"] for item in memory.recall_facts("favorite food")] == [
        "Actually, my favorite food is pasta now."]

    llm.generate.return_value = SimpleNamespace(content="L1")
    assert await memory.summarize_and_store([{
        "id": "episode-reasserted", "text": old["text"],
        "metadata": {"timestamp": now + 3600},
    }])
    assert [item["text"] for item in memory.recall_facts("favorite food")] == [
        "My favorite food is tofu."]

    expired_episode = {"id": "episode-exam", "text": "User: I have an exam tomorrow.\nBlob: Good luck.",
                       "metadata": {"timestamp": now - 4 * 86400}}
    llm.generate.return_value = SimpleNamespace(content="M1")
    assert await memory.summarize_and_store([expired_episode])
    assert store.middle.count() == 1
    assert memory.recall_middle("exam tomorrow") == []
    assert store.purge_expired_middle(now) == 1
    assert store.middle.count() == 0


@pytest.mark.asyncio
async def test_short_term_filter_preserves_archive_and_temporary_fact_stays_out_of_long_term(tmp_path):
    store = VectorStore(str(tmp_path / "memory"))
    old_time = time.time() - 10 * 86400
    store.store("User: I saw a blue bird.\nBlob: Neat.",
                {"type": "episodic", "timestamp": old_time})
    assert store.recall("blue bird", collection="episodic", min_timestamp=time.time() - 7 * 86400) == []
    assert len(store.recall("blue bird", collection="episodic")) == 1

    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="L1")))
    memory = SemanticMemory(store, llm)
    assert await memory.summarize_and_store([{
        "id": "dated", "text": "User: My exam is next Wednesday.\nBlob: Good luck.",
        "metadata": {"timestamp": time.time()},
    }])
    assert store.semantic.count() == 0
