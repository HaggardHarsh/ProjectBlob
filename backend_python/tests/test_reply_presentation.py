"""Reply control tags stay hidden and pending document requests show progress."""

import asyncio
from types import SimpleNamespace

import pytest

from blob.ai.attachments import AttachmentReader
from blob.ai.orchestrator import BlobOrchestrator
from blob.ipc import blob_service_pb2
from blob.memory.documents import DocumentLibrary
from blob.skills.registry import SkillRegistry
from test_attachments import orchestrator, text_pdf


@pytest.mark.parametrize(("marker", "mood"), [
    ("<emote>AMUSED</emote>", "PLAYFUL"),
    ("<Emote> amused </Emote>", "PLAYFUL"),
    ("(AMUSED)", "PLAYFUL"),
    ("<emote>GRATEFUL</emote>", "IDLE"),
    ("<emote>A VERY LONG UNSUPPORTED MOOD</emote>", "IDLE"),
    ("<emote></emote>", "IDLE"),
    ("<emote>AMUS", "IDLE"),
    ("<emot", "IDLE"),
])
def test_unknown_and_incomplete_emote_tags_are_never_visible(marker, mood):
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    assert instance._extract_emote("Hello. " + marker) == (mood, "Hello.")
    assert instance._extract_emote("Hello (world)") == ("IDLE", "Hello (world)")


def normal_chat():
    instance = orchestrator()
    instance.skill_registry = SkillRegistry()
    instance.screen_sampler = None
    instance._build_context = lambda text: "No personal facts"
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "drop", "followup", "saved"])
async def test_thinking_is_visible_while_answer_is_pending_and_cleared_after_reply(tmp_path, capsys, mode):
    path = tmp_path / "lesson.pdf"
    text_pdf(path, ["Voltage equals current times resistance"])
    instance = normal_chat()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def delayed_reply(messages, system_prompt):
        started.set()
        await finish.wait()
        return SimpleNamespace(content="Voltage equals current times resistance. <emote>AMUSED</emote>")

    instance.llm.generate_from_messages = delayed_reply
    if mode == "followup":
        instance._active_attachments = [str(path)]
    elif mode == "saved":
        instance.config.documents_dir_path = str(tmp_path / "library")
        prepared = AttachmentReader().prepare([str(path)], "Explain", vision=False)
        DocumentLibrary(instance.config.documents_dir_path).remember(prepared.sources)
    operation = (instance.handle_attachment_drop([str(path)]) if mode == "drop" else
                 instance.handle_user_message(blob_service_pb2.UserMessage(text="Explain voltage in lesson.pdf")))
    task = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        pending_output = capsys.readouterr().out
        assert "(Thinking...)" in pending_output
        assert instance._thinking_placeholder_visible
        instance.dispatch_emote.assert_any_await("THINKING")
        assert not task.done()
        finish.set()
        reply = await task
    finally:
        finish.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert reply == "Voltage equals current times resistance."
    assert not instance._thinking_placeholder_visible
    instance.dispatch_emote.assert_any_await("PLAYFUL")
    output = capsys.readouterr().out
    assert "<emote>" not in output and "AMUSED" not in output
    notification = instance.event_dispatcher.broadcast.call_args.args[0].notification.text
    assert notification == reply
    assert all("<emote>" not in turn["content"] for turn in instance._recent_turns)


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["<emote>AMUSED</emote>", "<emote>A VERY LONG UNSUPPORTED MOOD</emote>"])
async def test_split_unknown_tags_are_hidden_in_streamed_reply_and_notifications(capsys, marker):
    answer = "That sounds like a good way to work through your project. We can take it one step at a time."

    async def chunks(messages, system_prompt):
        for text in (answer, " ", *marker, " "):
            yield text

    instance = normal_chat()
    instance.llm.generate_from_messages_stream = chunks
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(text="Help me plan my project"))
    assert reply == answer
    output = capsys.readouterr().out
    assert "<emot" not in output and "AMUSED" not in output and "UNSUPPORTED" not in output
    assert output.count(answer) == 1
    assert output.count("Blob:") == 1
    assert not instance._thinking_placeholder_visible
    assert instance.event_dispatcher.broadcast.call_args.args[0].notification.text == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_failed_or_cancelled_model_request_clears_thinking_placeholder(capsys, failure):
    instance = normal_chat()
    started = asyncio.Event()

    async def pending_model(messages, system_prompt):
        started.set()
        if failure == "error":
            raise RuntimeError("Provider unavailable")
        await asyncio.Event().wait()

    instance.llm.generate_from_messages = pending_model
    task = asyncio.create_task(instance.handle_user_message(blob_service_pb2.UserMessage(text="Hello Blob")))
    await asyncio.wait_for(started.wait(), timeout=2)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="Provider unavailable"):
            await task
    assert not instance._thinking_placeholder_visible
    assert capsys.readouterr().out.endswith("\r\033[K")


@pytest.mark.asyncio
async def test_attachment_read_error_clears_thinking_before_error_reply(tmp_path, capsys):
    instance = orchestrator()
    reply = await instance.handle_user_message(blob_service_pb2.UserMessage(
        text="Explain the document", attachments=[str(tmp_path / "missing.pdf")]))
    assert "Select the file again" in reply
    assert not instance._thinking_placeholder_visible
    output = capsys.readouterr().out
    assert "(Thinking...)" in output
    assert "\r\033[K\nBlob:" in output
