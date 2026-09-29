from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from blob.memory.decay import DecayAlgorithm
from blob.memory.context import build_memory_view, MEMORY_CONTEXT_CHARS, RECALL_CONTEXT_CHARS
from blob.memory.semantic import SemanticMemory, is_temporary_fact
from blob.memory.vector_store import VectorStore


class FakeEpisodes:
    def __init__(self):
        self.items = {
            "one": {"text": "User: I prefer Python\nBlob: I prefer Java", "metadata": {"type": "episodic"}},
        }

    def get(self, **kwargs):
        eligible = [(key, item) for key, item in self.items.items() if not item["metadata"].get("consolidated")]
        return {
            "ids": [key for key, _ in eligible],
            "documents": [item["text"] for _, item in eligible],
            "metadatas": [item["metadata"] for _, item in eligible],
        }

    def update(self, ids, metadatas):
        self.items[ids[0]]["metadata"] = metadatas[0]


@pytest.mark.asyncio
async def test_semantic_consolidates_once_and_uses_only_user_statement():
    store = VectorStore.__new__(VectorStore)
    store.episodic = FakeEpisodes()
    stored = []
    store.store_grounded = lambda *args, **kwargs: stored.append((args, kwargs))
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="1")))
    memory = SemanticMemory(store, llm)

    assert await memory.consolidate_once() == 1
    assert await memory.consolidate_once() == 0
    assert len(stored) == 1
    prompt = llm.generate.call_args.args[0]
    assert "I prefer Python" in prompt
    assert "I prefer Java" not in prompt
    assert stored[0][0][2] == "semantic"


@pytest.mark.asyncio
async def test_failed_consolidation_is_retried():
    store = VectorStore.__new__(VectorStore)
    store.episodic = FakeEpisodes()
    store.store_grounded = lambda *args, **kwargs: None
    llm = SimpleNamespace(generate=AsyncMock(side_effect=[RuntimeError("offline"), SimpleNamespace(content="NONE")]))
    memory = SemanticMemory(store, llm)

    assert await memory.consolidate_once() == 0
    assert await memory.consolidate_once() == 1
    assert llm.generate.await_count == 2


def test_recall_refreshes_only_returned_memories():
    class Collection:
        def __init__(self):
            self.updated = []

        def count(self):
            return 2

        def query(self, **kwargs):
            return {
                "documents": [["first", "second"]],
                "metadatas": [[{"access_count": 0}, {"access_count": 0}]],
                "ids": [["a", "b"]],
                "distances": [[0.1, 0.9]],
            }

        def update(self, **kwargs):
            self.updated.append(kwargs["ids"][0])

    store = VectorStore.__new__(VectorStore)
    store.episodic = Collection()
    store.decay_algo = DecayAlgorithm()
    recalled = store.recall("query", top_k=1)
    assert [item["id"] for item in recalled] == ["a"]
    assert store.episodic.updated == ["a"]


def test_unrelated_nearest_neighbours_are_not_recalled_or_reinforced():
    class Collection:
        def __init__(self):
            self.updated = []

        def count(self):
            return 3

        def query(self, **kwargs):
            return {
                "documents": [["Python preference", "unrelated old chat", "concise replies"]],
                "metadatas": [[{"access_count": 0}, {"access_count": 50}, {"access_count": 0}]],
                "ids": [["a", "b", "c"]],
                "distances": [[0.7, 1.8, 1.1]],
            }

        def update(self, **kwargs):
            self.updated.extend(kwargs["ids"])

    store = VectorStore.__new__(VectorStore)
    store.episodic = Collection()
    store.decay_algo = DecayAlgorithm()

    recalled = store.recall("Python", top_k=3, max_distance=1.35)

    assert [item["id"] for item in recalled] == ["a", "c"]
    assert store.episodic.updated == ["a", "c"]


def test_memory_prompt_view_is_bounded_and_keeps_query_match_without_changing_source():
    long_user_message = "opening " * 300 + "My favorite anime is Trigun. " + "closing " * 300
    episode = f"User: {long_user_message}\nBlob: " + "unrelated reply " * 300
    facts = ["The user prefers concise answers."] * 2

    fact_view, episode_view = build_memory_view(facts, [episode], "favorite anime")

    assert fact_view.count("prefers concise answers") == 1
    assert "My favorite anime is Trigun" in episode_view
    assert episode_view.startswith("User: ")
    assert "\nBlob: " in episode_view
    assert len(fact_view) + len(episode_view) <= MEMORY_CONTEXT_CHARS
    assert long_user_message in episode

    _, recall_view = build_memory_view(facts, [episode], "remember favorite anime", user_only=True)
    assert "My favorite anime is Trigun" in recall_view
    assert "Blob:" not in recall_view
    assert len(fact_view) + len(recall_view) <= RECALL_CONTEXT_CHARS

    many_facts = ["fact " + str(number) + " " * 1000 for number in range(5)]
    many_episodes = [f"User: detail {number} " + "x" * 4000 + "\nBlob: " + "y" * 4000
                     for number in range(5)]
    fact_view, episode_view = build_memory_view(many_facts, many_episodes, "detail")
    assert all(f"detail {number}" in episode_view for number in range(5))
    assert len(fact_view) + len(episode_view) <= MEMORY_CONTEXT_CHARS


@pytest.mark.asyncio
async def test_consolidation_stores_duplicate_fact_once():
    store = VectorStore.__new__(VectorStore)
    store.episodic = FakeEpisodes()
    store.store_grounded = MagicMock()
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="1,1")))
    memory = SemanticMemory(store, llm)

    assert await memory.consolidate_once() == 1
    store.store_grounded.assert_called_once()


@pytest.mark.asyncio
async def test_temporary_weekday_claim_is_not_saved_as_durable_memory():
    store = SimpleNamespace(store_grounded=MagicMock())
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="1")))
    memory = SemanticMemory(store, llm)

    assert await memory.summarize_and_store([{"text": "User: Today is Tuesday. Keep it short.\nBlob: Got it."}])
    store.store_grounded.assert_called_once()
    assert store.store_grounded.call_args.args[0] == "Keep it short."
    assert is_temporary_fact("My exam is next Wednesday.")
    assert not is_temporary_fact("I work every Wednesday.")


@pytest.mark.asyncio
async def test_memory_extraction_rejects_invented_or_distorted_fact():
    store = SimpleNamespace(store_grounded=MagicMock())
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="1,999")))
    memory = SemanticMemory(store, llm)

    assert await memory.summarize_and_store([{"text": "User: I used to like Python.\nBlob: Nice."}])
    store.store_grounded.assert_called_once()
    assert store.store_grounded.call_args.args[0] == "I used to like Python."
    assert store.store_grounded.call_args.args[1]["grounded"] is True


@pytest.mark.asyncio
async def test_malformed_memory_selection_cannot_create_a_fact():
    store = SimpleNamespace(store_grounded=MagicMock())
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(
        content="1. The user likes Rust.")))
    memory = SemanticMemory(store, llm)

    assert not await memory.summarize_and_store([{"text": "User: I like Python.\nBlob: Nice."}])
    store.store_grounded.assert_not_called()


def test_existing_fact_is_not_reindexed_or_metadata_reset():
    class Collection:
        def __init__(self):
            self.saved = []

        def get(self, **kwargs):
            return {"ids": kwargs["ids"]}

        def upsert(self, **kwargs):
            self.saved.append(kwargs)

    store = VectorStore.__new__(VectorStore)
    store.semantic = Collection()

    assert store.store("I prefer Python", {"pinned": True}, collection="semantic",
                       memory_id="existing", skip_existing=True) == "existing"
    assert store.semantic.saved == []


@pytest.mark.asyncio
async def test_consolidation_deduplicates_repeated_user_messages():
    store = SimpleNamespace(store=MagicMock())
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="NONE")))
    memory = SemanticMemory(store, llm)

    assert await memory.summarize_and_store([
        {"text": "User: I like Python\nBlob: Great"},
        {"text": "User: i  like  python\nBlob: Nice"},
    ])
    prompt = llm.generate.call_args.args[0]
    assert prompt.count("1. I like Python") == 1
    assert "2. " not in prompt


def test_memory_survives_store_reopen(tmp_path, monkeypatch):
    import chromadb
    import blob.memory.vector_store as module

    class FixedEmbedding:
        def __call__(self, input):
            return [[float(len(text) % 5), float(text.count("a")), 1.0] for text in input]

        def embed_query(self, input):
            return self(input)

        def name(self):
            return "test-embedding"

        def is_legacy(self):
            return False

        def default_space(self):
            return "l2"

        def supported_spaces(self):
            return ["l2"]

    real_client = chromadb.PersistentClient

    class Client:
        def __init__(self, path):
            self.client = real_client(path=path)

        def get_or_create_collection(self, name):
            return self.client.get_or_create_collection(name, embedding_function=FixedEmbedding())

    monkeypatch.setattr(module.chromadb, "PersistentClient", Client)
    first = VectorStore(str(tmp_path))
    memory_id = first.store("I like Python", {"type": "semantic", "pinned": True}, collection="semantic")
    assert first.semantic_revision == 1
    first.store("Changed text", {"type": "semantic", "pinned": False}, collection="semantic",
                memory_id=memory_id, skip_existing=True)
    assert first.semantic_revision == 1
    saved = first.semantic.get(ids=[memory_id], include=["documents", "metadatas"])
    assert saved["documents"] == ["I like Python"]
    assert saved["metadatas"][0]["pinned"] is True
    del first
    second = VectorStore(str(tmp_path))
    recalled = second.recall("Python", collection="semantic")
    assert [item["id"] for item in recalled] == [memory_id]
    other_id = second.store("I like Rust", {"type": "semantic", "pinned": True}, collection="semantic")
    assert {item["id"] for item in second.recall("programming", top_k=2, collection="semantic")} == {memory_id, other_id}
    metadata = second.semantic.get(ids=[memory_id, other_id], include=["metadatas"])["metadatas"]
    assert sorted(item["access_count"] for item in metadata) == [1, 2]
