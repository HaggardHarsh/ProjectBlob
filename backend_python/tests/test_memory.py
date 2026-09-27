from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.memory.decay import DecayAlgorithm
from blob.memory.semantic import SemanticMemory
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
    store.store = lambda *args, **kwargs: stored.append((args, kwargs))
    llm = SimpleNamespace(generate=AsyncMock(return_value=SimpleNamespace(content="I prefer Python")))
    memory = SemanticMemory(store, llm)

    assert await memory.consolidate_once() == 1
    assert await memory.consolidate_once() == 0
    assert len(stored) == 1
    prompt = llm.generate.call_args.args[0]
    assert "I prefer Python" in prompt
    assert "I prefer Java" not in prompt
    assert stored[0][1]["collection"] == "semantic"


@pytest.mark.asyncio
async def test_failed_consolidation_is_retried():
    store = VectorStore.__new__(VectorStore)
    store.episodic = FakeEpisodes()
    store.store = lambda *args, **kwargs: None
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
    del first
    second = VectorStore(str(tmp_path))
    recalled = second.recall("Python", collection="semantic")
    assert [item["id"] for item in recalled] == [memory_id]
