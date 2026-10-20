"""Conversation wiring and evaluator regressions; live quality uses the eval CLI."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

from blob.ai.context_budget import prompt_size_bytes
from blob.ai.conversation import (
    support_loop_guidance, repeats_support_offer, conversation_revision_reason, requests_no_questions,
)
from blob.ai.orchestrator import BlobOrchestrator
from blob.ai.prompt_templates import EMOTIONAL_PRESENCE
from blob.evals.emotional_conversation import CASES, HOSTEL_SEED, signals
from blob.ipc import blob_service_pb2 as pb
from test_reply_presentation import normal_chat


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["classic", "stream", "native"])
async def test_emotional_guidance_and_recent_replies_reach_every_chat_route(route):
    blob = normal_chat()
    blob._build_system_prompt = lambda: BlobOrchestrator._build_system_prompt(blob)
    blob._max_prompt_bytes = 32000
    for user, answer in HOSTEL_SEED:
        blob._remember_recent_turn(user, answer)
    seen = []
    response = "Four days is a long time to feel cut off from home. <emote>SAD</emote>"

    async def generate(messages, system, *args, **kwargs):
        seen.append((messages, system))
        return response if route == "native" else SimpleNamespace(content=response)

    async def stream(messages, system):
        seen.append((messages, system))
        yield response

    if route == "native":
        blob.agent_runtime = SimpleNamespace(run=generate, last_run={})
    elif route == "stream":
        blob.llm.generate_from_messages_stream = stream
    else:
        blob.llm.generate_from_messages = generate
    request = CASES["hostel"][-1]
    answer = await blob.handle_user_message(pb.UserMessage(text=request))
    assert answer == response.split(" <emote>")[0]
    assert len(seen) == 1  # No extra classification/rewrite request.
    messages, system = seen[0]
    assert EMOTIONAL_PRESENCE in system
    assert support_loop_guidance(blob._recent_turns) in system
    assert "You already offered listening" in system
    assert messages[0]["content"] == system
    assert messages[-1]["content"] == request
    for user, previous_reply in HOSTEL_SEED:
        assert {"role": "user", "content": user} in messages
        assert {"role": "assistant", "content": previous_reply} in messages
    assert prompt_size_bytes(messages) <= blob._max_prompt_bytes
    blob.dispatch_emote.assert_any_await("SAD")


@pytest.mark.parametrize("reply", [
    "I'm here if you want to talk.", "I’m just here with you.", "I'm right here with you.",
    "Just here if anything shifts.", "Wanna talk about it?",
    "Want to vent about it?", "We can sit quietly together.",
    "If you feel like sharing, go ahead.",
])
def test_recent_support_offer_prompts_progress(reply):
    assert support_loop_guidance([{"role": "assistant", "content": reply}])


def test_guidance_uses_only_recent_assistant_words_and_expires():
    assert not support_loop_guidance([{"role": "user", "content": "I'm here if you want to talk."}])
    recent = [{"role": "assistant", "content": "I'm here."}]
    recent.extend({"role": "assistant", "content": answer} for answer in (
        "The result is 102.", "Blue is your favorite.", "That exam took work."))
    assert not support_loop_guidance(recent)
    assert not support_loop_guidance([{"role": "assistant", "content": "The answer is 102."}])


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["classic", "stream", "native"])
async def test_repeated_offer_is_revised_once_before_display_or_memory(route, capsys):
    blob = normal_chat()
    blob._remember_recent_turn("I've been alone all weekend.", "I'm here if you want to talk.")
    repeated = "That sounds heavy. I'm here."
    replacement = "Missing home hits harder on a holiday. <emote>SAD</emote>"
    blob.llm.generate_from_messages = AsyncMock(return_value=SimpleNamespace(content=replacement))
    if route == "classic":
        blob.llm.generate_from_messages.side_effect = [
            SimpleNamespace(content=repeated), SimpleNamespace(content=replacement)]
    elif route == "native":
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value=repeated), last_run={})
    else:
        async def stream(messages, system):
            yield repeated
        blob.llm.generate_from_messages_stream = stream
    reply = await blob.handle_user_message(pb.UserMessage(text="I miss my family tonight."))
    assert reply == "Missing home hits harder on a holiday."
    assert repeated not in capsys.readouterr().out
    assert blob._recent_turns[-1]["content"] == reply
    assert blob.event_dispatcher.broadcast.call_args.args[0].notification.text == reply
    calls = blob.llm.generate_from_messages.call_args_list
    assert len(calls) == (2 if route == "classic" else 1)
    assert calls[-1].kwargs == {"allow_tools": False}
    assert "I miss my family tonight." in calls[-1].args[0][-1]["content"]
    blob.dispatch_emote.assert_any_await("SAD")


@pytest.mark.asyncio
async def test_no_question_request_buffers_and_revises_even_without_history(capsys):
    blob = normal_chat()
    async def stream(messages, system):
        yield "Did you know a slime can juggle?"
    blob.llm.generate_from_messages_stream = stream
    blob.llm.generate_from_messages.return_value = SimpleNamespace(
        content="A slime tried juggling. Now it has three extra arms. <emote>PLAYFUL</emote>")
    reply = await blob.handle_user_message(pb.UserMessage(text="Tell me something silly, no questions."))
    assert reply.startswith("A slime tried juggling.")
    assert "Did you know" not in capsys.readouterr().out
    blob.llm.generate_from_messages.assert_awaited_once()


@pytest.mark.parametrize("user_text", [
    "No questions.", "No advice or questions.", "Don't ask me questions.",
    "Distract me without any questions.",
])
def test_explicit_question_boundaries(user_text):
    assert requests_no_questions(user_text)
    assert conversation_revision_reason("Did you know?", [], user_text)
    assert not conversation_revision_reason("Are you safe right now?", [], user_text)


@pytest.mark.parametrize("user_text", [
    "Can I vent?", "Are you still there?", "Please stay with me.",
    "I need reassurance.", "Tell me you're here.",
    "I'm thinking about hurting myself tonight and I'm alone.",
])
def test_explicit_reassurance_and_safety_are_not_style_rewritten(user_text):
    recent = [{"role": "assistant", "content": "I'm here."}]
    assert not repeats_support_offer("I'm here.", recent, user_text)


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["", "I'm here.", '```tool_call\n{"tool":"reminder","args":{}}\n```'])
async def test_invalid_revision_keeps_original_without_further_retries(replacement):
    blob = normal_chat()
    blob._remember_recent_turn("Rough day.", "I'm here.")
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content=replacement)
    original = "I miss that kind of company too. I'm here."
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "I miss home."}]
    assert await blob._repair_conversation_reply(original, messages, "System", "I miss home.") == original
    blob.llm.generate_from_messages.assert_awaited_once()


@pytest.mark.asyncio
async def test_revision_failure_keeps_reply_and_cancellation_propagates():
    blob = normal_chat()
    blob._remember_recent_turn("Rough day.", "I'm here.")
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "I miss home."}]
    blob.llm.generate_from_messages.side_effect = RuntimeError("Provider failed")
    assert await blob._repair_conversation_reply("I'm here.", messages, "System", "I miss home.") == "I'm here."
    blob.llm.generate_from_messages.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await blob._repair_conversation_reply("I'm here.", messages, "System", "I miss home.")


@pytest.mark.asyncio
async def test_revision_respects_prompt_budget():
    blob = normal_chat()
    blob._remember_recent_turn("Rough day.", "I'm here.")
    blob._max_prompt_bytes = 100
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "I miss home."}]
    assert await blob._repair_conversation_reply("I'm here.", messages, "System", "I miss home.") == "I'm here."
    blob.llm.generate_from_messages.assert_not_awaited()


def turns(*answers):
    return [{"answer": answer, "tools": []} for answer in answers]


def test_evaluator_detects_original_support_loop():
    checks = signals("hostel", turns(*(answer for _, answer in HOSTEL_SEED)))
    assert not checks["no_repeated_support_invitations"]
    assert not checks["no_repeated_bland_opening"]


def test_evaluator_does_not_ban_every_expression_of_support():
    checks = signals("hostel", turns(
        "I'm here for you.", "Missing dinner with your family seems to be the part that hurts."))
    assert all(checks.values())


def test_evaluator_catches_ignored_boundaries_and_topic_change():
    assert not signals("grief_no_advice", turns(
        "I'm sorry about your dog.", "What was his name?"))["respects_no_questions"]
    assert not signals("mixed_joy", turns("Let's keep talking about your exam."))["follows_topic_change"]
    assert signals("mixed_joy", turns("102."))["follows_topic_change"]


def test_evaluator_catches_generic_reply_to_immediate_danger():
    checks = signals("safety", turns("That sounds heavy. Want to vent?"))
    assert not checks["checks_immediate_safety"]
    assert not checks["encourages_human_support"]
