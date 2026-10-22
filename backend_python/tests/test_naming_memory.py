"""Naming instructions survive poor retrieval, corrections, and restarts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from blob.evals.document_memory import OfflineEmbedding, make_blob
from blob.ipc import blob_service_pb2 as pb
from blob.memory.semantic import SemanticMemory
from blob.memory.vector_store import VectorStore


@pytest.mark.parametrize("statement", [
    "Call me Cloudie.", "Please call me Cloudie.", "Hey Blob, please call me Cloudie.",
    "You can call me Cloudie.", "I want you to call me Cloudie.",
    "I'd like you to call me Cloudie.", "My name is Cloudie.",
])
def test_naming_instruction_is_saved_without_consolidation(tmp_path, statement):
    store = VectorStore(str(tmp_path / "memory"), embedding_function=OfflineEmbedding())
    memory = SemanticMemory(store, None)
    memory.remember_explicit_statements(statement, "source", 1000.0)
    records = store.list_active("semantic", topic_keys=("name",))
    assert [item["text"] for item in records] == [statement]
    assert records[0]["metadata"]["source_episode_id"] == "source"
    assert records[0]["metadata"]["grounded"] is True
    assert "expires_at" not in records[0]["metadata"]


@pytest.mark.parametrize("statement", [
    "Why do you call me Cloudie?", "Can you call me Cloudie?",
    "If I asked you to call me Cloudie, what would you say?",
    "My friend said call me Cloudie.", 'The character says "call me Cloudie".',
    "Call me Cloudie today.", "Call me Cloudie tomorrow.",
])
def test_questions_reported_speech_and_temporary_names_are_not_permanent(tmp_path, statement):
    store = VectorStore(str(tmp_path / "memory"), embedding_function=OfflineEmbedding())
    memory = SemanticMemory(store, None)
    memory.remember_explicit_statements(statement)
    assert memory.profile_context() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_followup_keeps_original_user_instruction_despite_empty_search(tmp_path, native):
    first = make_blob(tmp_path)
    instruction = "Please call me Cloudie."
    await first.handle_user_message(pb.UserMessage(text=instruction))
    assert instruction in first.semantic.profile_context()
    # Restart before the memory model has consolidated any episodes.
    blob = make_blob(tmp_path)
    blob.semantic.recall_facts = Mock(return_value=[])
    blob.semantic.recall_middle = Mock(return_value=[])
    blob.episodic.recall_relevant = Mock(return_value=[])
    blob._get_style_facts = Mock(return_value=[])
    provider = AsyncMock(return_value=("I call you Cloudie." if native else
                                      SimpleNamespace(content="I call you Cloudie.")))
    if native:
        blob.agent_runtime = SimpleNamespace(run=provider, last_run={})
    else:
        blob.llm.generate_from_messages = provider
    await blob.handle_user_message(pb.UserMessage(text="What do you call me?"))
    await blob.handle_user_message(pb.UserMessage(text="Why that so"))
    messages, system = provider.call_args.args[:2]
    assert instruction in system
    assert "exact user statement" in system
    assert {"role": "assistant", "content": "I call you Cloudie."} in messages
    assert messages[-1]["content"] == "Why that so"
    assert "not itself a correction" in system
    assert "Cloudie" not in blob._build_context("Why that so")
    # The evidence also survives when the entire original exchange is evicted.
    for _ in range(8):
        blob._remember_recent_turn("Unrelated conversation.", "An unrelated reply.")
    await blob.handle_user_message(pb.UserMessage(text="Why that so"))
    assert instruction in provider.call_args.args[1]


def test_old_archives_recover_only_latest_user_instruction(tmp_path):
    first = make_blob(tmp_path)
    first.episodic.add_episode("Call me Cloudie.", "Okay.")
    first.episodic.add_episode("Actually, call me Sunny.", "Okay.")
    first.episodic.add_episode("Thanks", "Call me Invented.")
    first.episodic.add_episode("Call me Question?", "Okay.")
    restarted = make_blob(tmp_path)
    context = restarted.semantic.profile_context()
    assert "Actually, call me Sunny." in context
    assert "Cloudie" not in context and "Invented" not in context and "Question" not in context
    assert "Sunny" in restarted.semantic.document_context("Explain this page.")


def test_corrections_negation_and_reassertion_survive_restarts(tmp_path):
    blob = make_blob(tmp_path)
    for statement in [
        "Call me Cloudie.", "Actually, call me Sunny.", "Don't call me Sunny.",
        "Call me Cloudie.",
    ]:
        blob._remember_turn(statement, "Okay.")
        context = make_blob(tmp_path).semantic.profile_context()
        assert context.endswith(statement)
        assert len(blob.vector_store.list_active("semantic", topic_keys=("name",))) == 1


def test_older_archive_cannot_replace_newer_saved_preference(tmp_path):
    blob = make_blob(tmp_path)
    blob.episodic.add_episode("Call me Cloudie.", "Okay.")
    blob.semantic.remember_explicit_statements("Call me Sunny.", source_timestamp=10**10)
    restarted = make_blob(tmp_path)
    assert "Sunny" in restarted.semantic.profile_context()
    assert "Cloudie" not in restarted.semantic.profile_context()


def test_forgotten_name_is_not_restored_from_archive_on_restart(tmp_path):
    blob = make_blob(tmp_path)
    blob._remember_turn("Call me Cloudie.", "Okay.")
    record = blob.vector_store.list_active("semantic", topic_keys=("name",))[0]
    blob.vector_store.forget_personal_memory("semantic", record["id"])
    assert make_blob(tmp_path).semantic.profile_context() == ""


@pytest.mark.asyncio
async def test_background_consolidation_cannot_demote_a_saved_name(tmp_path):
    blob = make_blob(tmp_path)
    blob._remember_turn("Call me Cloudie.", "Okay.")
    blob.semantic.llm = SimpleNamespace(generate=AsyncMock(
        return_value=SimpleNamespace(content="M1")))
    assert await blob.semantic.consolidate_once() == 1
    assert "Call me Cloudie." in blob.semantic.profile_context()
    assert blob.vector_store.list_active("middle", topic_keys=("name",)) == []
