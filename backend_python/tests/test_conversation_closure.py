"""Declining a task and acknowledging closure cannot resurrect recalled work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from blob.ai.conversation import conversation_reply
from blob.ai.prompt_templates import SYSTEM_PROMPT, CONVERSATION_CONTINUITY
from blob.ipc import blob_service_pb2 as pb
from test_reply_presentation import normal_chat


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_declined_email_stays_closed_after_acknowledgement(native):
    blob = normal_chat()
    blob._build_context = Mock(side_effect=AssertionError("Social reply retrieved stale email"))
    blob._handle_attachment_message = AsyncMock(side_effect=AssertionError("Old attachment reopened"))
    blob._active_attachments = ["/synthetic/old.pdf"]
    blob._public_lookup_policy = object()
    if native:
        blob.agent_runtime = SimpleNamespace(run=AsyncMock())
    blob._remember_recent_turn("what do u call me bby", "I call you Cloudie.")
    assert await blob.handle_user_message(pb.UserMessage(text="yayy")) == "Yay!"
    blob._remember_recent_turn("Earlier chat", "Want me to draft that email for you?")
    assert "leave that" in await blob.handle_user_message(pb.UserMessage(text="nah not really. We are done with that"))
    for text in ("sure", "okay", "thanks"):
        answer = await blob.handle_user_message(pb.UserMessage(text=text))
        assert "email" not in answer.lower() and "Subject:" not in answer
    assert blob._public_lookup_policy is None
    assert blob._recent_turns[-2]["content"] == "thanks"
    blob._build_context.assert_not_called()
    blob.llm.generate_from_messages.assert_not_awaited()
    blob._handle_attachment_message.assert_not_awaited()
    if native:
        blob.agent_runtime.run.assert_not_awaited()


@pytest.mark.parametrize("text", ["No thanks", "I don't need it anymore.", "We're done with that.",
    "Never mind", "skip it please", "nah not really. We are done with that", "dont do that"])
def test_whole_message_closures(text):
    assert conversation_reply(text, []) == "Got it. I'll leave that there."


@pytest.mark.parametrize("text", ["No, rewrite it more casually.", "Don't send it, just draft it.",
    "We're done with that. Now explain Ohm's law.", "Sure, draft the email now.", "No seats available?",
    "I don't need an email, but can you make a list?", "/reminders cancel abc", "sure?"])
def test_corrections_and_explicit_new_requests_reach_normal_chat(text):
    assert conversation_reply(text, []) is None


@pytest.mark.parametrize("text", ["thanks", "thank you"])
def test_gratitude_is_not_acceptance_of_an_offer(text):
    assert conversation_reply(text, [{"role": "assistant", "content": "Want me to draft the email?"}]) == "You're welcome."


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_fresh_offer_can_still_be_accepted_and_closed_task_can_be_explicitly_reopened(native):
    blob = normal_chat()
    blob._remember_recent_turn("Can you help with an email?", "Want me to draft it?")
    if native:
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value="Here is your requested draft."), last_run={})
    else:
        blob.llm.generate_from_messages.return_value = SimpleNamespace(content="Here is your requested draft.")
    assert "draft" in await blob.handle_user_message(pb.UserMessage(text="sure"))
    await blob.handle_user_message(pb.UserMessage(text="never mind"))
    assert "draft" in await blob.handle_user_message(pb.UserMessage(text="Actually draft that email now."))
    if native:
        assert blob.agent_runtime.run.await_count == 2
    else:
        assert blob.llm.generate_from_messages.await_count == 2


def test_continuity_rule_covers_chat_and_file_followups():
    assert "tasks stay closed" in SYSTEM_PROMPT
    # File and saved-result prompts append the same shared continuity rule.
    assert "Declines close tasks until reopened" in CONVERSATION_CONTINUITY
    assert "Recalled requests aren't pending work" in CONVERSATION_CONTINUITY
