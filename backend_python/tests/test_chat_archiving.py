"""Every authored chat has a durable source, independent of screen capture or model success."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.evals.document_memory import make_blob
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyControls


def chat_at(root, *, shielded=False, controls=None):
    blob = make_blob(root)
    blob.event_dispatcher = SimpleNamespace(broadcast=AsyncMock())
    blob.dispatch_emote = AsyncMock()
    blob.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content="Got it. <emote>HAPPY</emote>"))
    if shielded:
        blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    if controls:
        blob.controls = blob.vector_store.controls = blob.llm.controls = controls
    return blob


def documents(blob):
    return blob.vector_store.episodic.get(include=["documents"])["documents"]


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["classic", "hermes"])
@pytest.mark.parametrize("shielded", [False, True])
async def test_date_marks_and_short_replies_survive_restart_once_each(tmp_path, runtime, shielded):
    blob = chat_at(tmp_path, shielded=shielded)
    if runtime == "hermes":
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value="Got it. <emote>HAPPY</emote>"), last_run={})
    statements = ["I went on a date with my girlfriend.", "My mid sem marks were 24/30 in Signals and 27/30 in Analog.", "Thanks"]
    replies = [await blob.handle_user_message(pb.UserMessage(text=text)) for text in statements]
    archived = blob.vector_store.episodic.get(include=["documents", "metadatas"])
    for memory_id, text, metadata in zip(archived["ids"], archived["documents"], archived["metadatas"]):
        metadata["timestamp"] = time.time() - (14 if statements[1] in text else 2) * 86400
        blob.vector_store.store(text, metadata, memory_id=memory_id)
    restarted = chat_at(tmp_path)
    assert set(documents(restarted)) == {f"User: {text}\nBlob: {reply}" for text, reply in zip(statements, replies)}
    assert restarted.vector_store.episodic_user.count() == 3
    context = restarted._build_context("Do you remember my date and mid sem marks?")
    assert statements[0] in context and statements[1] in context


@pytest.mark.asyncio
async def test_identical_chat_messages_are_separate_archived_turns(tmp_path):
    blob = chat_at(tmp_path, shielded=True)
    replies = [await blob.handle_user_message(pb.UserMessage(text="Thanks")) for _ in range(2)]
    assert sorted(documents(blob)) == sorted("User: Thanks\nBlob: " + reply for reply in replies)
    assert blob.vector_store.episodic_user.count() == 2


@pytest.mark.asyncio
async def test_oversized_request_is_archived_without_truncation_before_budget_rejection(tmp_path):
    blob = chat_at(tmp_path)
    blob._max_prompt_bytes = 4096
    text = ("My marks were 24/30. " + "More detail. " * 1000).rstrip()
    reply = await blob.handle_user_message(pb.UserMessage(text=text))
    assert "narrow or split" in reply
    assert documents(chat_at(tmp_path)) == [f"User: {text}\nBlob: {reply}"]
    blob.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_incoming_message_is_durable_before_the_model_replies(tmp_path, failure):
    blob = chat_at(tmp_path, shielded=True)
    started = asyncio.Event()
    text = "My mid sem marks were 24/30 in Signals."

    async def pending(messages, system):
        started.set()
        if failure == "error":
            raise RuntimeError("Synthetic provider failure")
        await asyncio.Event().wait()

    blob.llm.generate_from_messages = pending
    task = asyncio.create_task(blob.handle_user_message(pb.UserMessage(text=text)))
    try:
        await asyncio.wait_for(started.wait(), 3)
        assert documents(chat_at(tmp_path)) == ["User: " + text]
        if failure == "cancel":
            task.cancel()
        with pytest.raises(RuntimeError if failure == "error" else asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert documents(chat_at(tmp_path)) == ["User: " + text]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Thanks", "Do a happy face", "What's on my screen?"])
async def test_direct_replies_and_early_tool_failures_are_archived(tmp_path, text):
    blob = chat_at(tmp_path, shielded=True)
    reply = await blob.handle_user_message(pb.UserMessage(text=text))
    assert documents(chat_at(tmp_path)) == [f"User: {text}\nBlob: {reply}"]
    blob.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_queued_message_keeps_its_own_source_when_cancelled(tmp_path):
    blob = chat_at(tmp_path)
    started, finish = asyncio.Event(), asyncio.Event()
    async def pending(messages, system):
        started.set()
        await finish.wait()
        return SimpleNamespace(content="The first reply.")
    blob.llm.generate_from_messages = pending
    first = asyncio.create_task(blob.handle_user_message(pb.UserMessage(text="My marks were 24/30.")))
    second = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        second = asyncio.create_task(blob.handle_user_message(pb.UserMessage(text="I went on a date.")))
        await asyncio.sleep(0)
        assert len(documents(blob)) == 2
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        finish.set()
        assert await first == "The first reply."
    finally:
        finish.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
    assert set(documents(chat_at(tmp_path))) == {
        "User: My marks were 24/30.\nBlob: The first reply.", "User: I went on a date."}


@pytest.mark.asyncio
async def test_chat_is_readable_from_a_fresh_process(tmp_path):
    blob = chat_at(tmp_path, shielded=True)
    await blob.handle_user_message(pb.UserMessage(text="My marks were 24/30."))
    script = (
        "import json,sys; from pathlib import Path; from blob.evals.document_memory import make_blob; "
        "blob=make_blob(Path(sys.argv[1])); print(json.dumps(blob.vector_store.episodic.get(include=['documents'])['documents']))"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=environment,
                            capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(result.stdout) == ["User: My marks were 24/30.\nBlob: Got it."]


@pytest.mark.asyncio
async def test_initial_storage_failure_is_visible_and_does_not_process_the_request(tmp_path, monkeypatch):
    blob = chat_at(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("Synthetic full disk")
    monkeypatch.setattr(blob.episodic, "add_user_message", fail)
    reply = await blob.handle_user_message(pb.UserMessage(text="My marks were 24/30."))
    assert "couldn't save your message" in reply and "haven't processed it" in reply
    blob.llm.generate_from_messages.assert_not_awaited()
    assert blob.event_dispatcher.broadcast.call_args.args[0].notification.text == reply
    assert documents(blob) == []


@pytest.mark.asyncio
async def test_reply_storage_failure_keeps_the_user_source_and_warns_both_clients(tmp_path, monkeypatch, capsys):
    blob = chat_at(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("Synthetic reply write failure")
    monkeypatch.setattr(blob.episodic, "complete_episode", fail)
    reply = await blob.handle_user_message(pb.UserMessage(text="I went on a date."))
    assert "Got it." in reply and "couldn't save my reply" in reply
    assert documents(chat_at(tmp_path)) == ["User: I went on a date."]
    assert blob.event_dispatcher.broadcast.call_args.args[0].notification.text == reply
    assert reply in capsys.readouterr().out
    blob.llm.generate_from_messages.assert_awaited_once()


@pytest.mark.asyncio
async def test_derived_fact_failure_does_not_lose_archived_chat(tmp_path, monkeypatch):
    blob = chat_at(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("Synthetic derived-memory failure")
    monkeypatch.setattr(blob.semantic, "remember_explicit_statements", fail)
    reply = await blob.handle_user_message(pb.UserMessage(text="My subjects are Signals and Analog."))
    assert documents(chat_at(tmp_path)) == ["User: My subjects are Signals and Analog.\nBlob: " + reply]


@pytest.mark.asyncio
async def test_privacy_pause_and_forgetting_do_not_archive_or_restore_control_output(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    blob = chat_at(tmp_path, controls=controls)
    await blob.handle_user_message(pb.UserMessage(text="My marks were 24/30."))
    assert len(documents(blob)) == 1
    await blob.handle_user_message(pb.UserMessage(text="/memory forget all"))
    assert documents(blob) == []
    controls.update(paused=True)
    reply = await blob.handle_user_message(pb.UserMessage(text="This paused message must remain private."))
    assert "Privacy pause" in reply
    assert documents(blob) == []


@pytest.mark.asyncio
async def test_forgetting_during_a_reply_cannot_recreate_the_source(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    blob = chat_at(tmp_path, controls=controls)
    async def forget_during_reply(messages, system):
        await blob.handle_user_message(pb.UserMessage(text="/memory forget all"))
        return SimpleNamespace(content="A late reply.")
    blob.llm.generate_from_messages = forget_during_reply
    await blob.handle_user_message(pb.UserMessage(text="I went on a date."))
    assert documents(chat_at(tmp_path)) == []


def test_completion_preserves_source_timestamp_and_does_not_resurrect_a_deleted_episode(tmp_path):
    blob = chat_at(tmp_path)
    episode = blob.episodic.add_user_message("My marks were 24/30.")
    before = blob.vector_store.episodic.get(ids=[episode], include=["metadatas"])["metadatas"][0]
    assert blob.episodic.complete_episode(episode, "Got it.")
    after = blob.vector_store.episodic.get(ids=[episode], include=["metadatas"])["metadatas"][0]
    assert after["timestamp"] == before["timestamp"]
    assert after["consolidated"] == before["consolidated"]
    blob.vector_store.forget_personal_memory("episodic", episode)
    assert not blob.episodic.complete_episode(episode, "A delayed reply.")
    assert documents(blob) == []


def test_consolidation_does_not_overwrite_metadata_from_a_completed_reply(tmp_path):
    blob = chat_at(tmp_path)
    episode = blob.episodic.add_user_message("My marks were 24/30.")
    snapshot = blob.vector_store.unconsolidated_episodes()
    assert blob.episodic.complete_episode(episode, "Got it.")
    blob.vector_store.mark_consolidated(snapshot)
    current = blob.vector_store.episodic.get(ids=[episode], include=["documents", "metadatas"])
    assert current["documents"] == ["User: My marks were 24/30.\nBlob: Got it."]
    assert current["metadatas"][0]["user_only"] is False
    assert current["metadatas"][0]["consolidated"] is True
