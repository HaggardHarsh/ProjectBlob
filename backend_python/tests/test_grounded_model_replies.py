"""Current AI-product questions need sources; protocol text is never an action."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ai.response_format import FORMAT_FAILURE, has_tool_protocol
from blob.ai.web_grounding import live_product_query, requested_system_tools
from blob.agents.hermes import AgentRuntimeError
from blob.config import BlobConfig
from blob.ipc import blob_service_pb2 as pb
from blob.skills.base import SkillResult
from blob.skills.builtin.web import WebSearchSkill, WebReadSkill, web_result
from blob.skills.registry import SkillRegistry
from test_agent_runtime import bridge, reply, run
from test_reply_presentation import normal_chat

RAW_REPLY = ("It's okay—nothing special.<|tool_calls_section_begin|><|tool_call_begin|>blob_shell_command"
    "<|tool_argument_begin|>command<|tool_argument_value|>echo done<|tool_call_end|><|tool_calls_section_end|>Done. "
    "<|tool_responses_section_begin|><|tool_response_begin|>done<|tool_response_end|><|tool_responses_section_end|>"
    "<|tool_calls_section_begin|><|tool_call_begin|>blob_reminder<|tool_argument_begin|>action<|tool_argument_value|>list"
    "<|tool_call_end|><|tool_calls_section_end|><|emote>IDLE</emote>")


@pytest.mark.parametrize("text, subject", [
    ("what is gemini 4 argon", "gemini 4 argon"),
    ("What's Claude Sonnet 4.7?", "Claude Sonnet 4.7"),
    ("Is GPT-6.1 Sol good?", "GPT-6.1 Sol"),
    ("Compare Qwen 7 and DeepSeek 5", "Qwen 7"),
])
def test_ai_product_questions_get_live_queries(text, subject):
    assert subject.lower() in live_product_query(text).lower()


@pytest.mark.parametrize("text", ["Hello", "What is Ohm's law?", "I use Gemini to study every day.", "I use GPT", "Gemini is great",
    "What do you remember about my GPT subscription?", "Write an email about Gemini", "What are llamas?"])
def test_greetings_personal_statements_and_writing_tasks_are_not_auto_searched(text):
    assert live_product_query(text) is None


def test_short_followup_uses_user_product_name_not_assistant_inventions():
    recent = [{"role": "user", "content": "What is Gemini 4 Argon?"},
              {"role": "assistant", "content": "Invented private codename with imaginary performance."}]
    query = live_product_query("crazy, is it good?", recent)
    assert "Gemini 4 Argon" in query and "benchmarks" in query
    assert "private" not in query and "imaginary" not in query
    recent += [{"role": "user", "content": "Let's talk about lunch."}]
    assert live_product_query("Is it good?", recent) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_sources_are_fetched_before_model_even_without_explicit_search(tmp_path, native):
    blob = normal_chat()
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    search = WebSearchSkill(BlobConfig())
    search.async_execute = AsyncMock(return_value=web_result({"results": [
        {"url": "https://ai.google.dev.attacker.example/guess"},
        {"url": "https://ai.google.dev/model"}]}))
    read = WebReadSkill()
    read.async_execute = AsyncMock(return_value=web_result({"url": "https://ai.google.dev/model",
        "text": "Verified current source evidence: Gemini 4 Argon " + "capabilities and limitations. " * 10}))
    blob.skill_registry.register(search)
    blob.skill_registry.register(read)
    blob._remember_recent_turn("What is Gemini 4 Argon?", "Earlier unsupported description.")
    if native:
        async def answer(messages, system, tools, execute, event):
            assert {tool["name"] for tool in tools} == {"blob_web_search", "blob_web_read"}
            assert "Verified current source evidence" in messages[-1]["content"]
            denied = await execute("blob_shell_command", {"command": "echo done"})
            assert not denied.success
            return "See the verified source: https://ai.google.dev/model"
        blob.agent_runtime = SimpleNamespace(run=answer, last_run={})
    else:
        blob.llm.generate_from_messages.return_value = SimpleNamespace(content="See https://ai.google.dev/model")
    result = await blob.handle_user_message(pb.UserMessage(text="crazy, is it good?"))
    assert "https://ai.google.dev/model" in result
    assert "Gemini 4 Argon" in search.async_execute.call_args.args[0]["query"]
    read.async_execute.assert_awaited_once_with({"url": "https://ai.google.dev/model"})
    if native:
        assert blob.agent_runtime.last_run["preflight_tools"] == [
            {"name": "web_search", "success": True}, {"name": "web_read", "success": True}]
    else:
        assert "Verified current source evidence" in blob.llm.generate_from_messages.call_args.args[0][-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["search", "read", "empty", "irrelevant"])
async def test_missing_fresh_evidence_never_falls_back_to_guessing(tmp_path, failure):
    blob = normal_chat()
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    search = WebSearchSkill(BlobConfig())
    search.async_execute = AsyncMock(return_value=(SkillResult("Unavailable", False) if failure == "search" else
        web_result({"results": [] if failure == "empty" else [{"url": "https://example.com/"}]})))
    read = WebReadSkill()
    read.async_execute = AsyncMock(return_value=(web_result({"url": "https://example.com/", "text": "Gemini 3 is an older model. " * 10})
        if failure == "irrelevant" else SkillResult("Blocked", False)))
    blob.skill_registry.register(search)
    blob.skill_registry.register(read)
    answer = await blob.handle_user_message(pb.UserMessage(text="What is Gemini 4 Argon?"))
    assert "couldn't verify" in answer
    blob.llm.generate_from_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_provider_protocol_is_retried_not_executed(tmp_path):
    runtime = bridge(tmp_path, "emit({'type':'model','request':{'messages':request['messages']}})\n"
        "response=receive()\nanswer=response['result']['choices'][0]['message']['content']\n"
        "assert '<|tool_' not in answer\nemit({'type':'final','answer':answer,'completed':True})\n")
    runtime.llm._create.side_effect = [reply(RAW_REPLY), reply("A clean answer.")]
    execute = AsyncMock()
    try:
        assert await run(runtime, execute=execute) == "A clean answer."
        execute.assert_not_awaited()
        assert runtime.last_run["tools"] == []
        assert runtime.last_run["model_calls"] == 2 and runtime.last_run["format_retries"] == 1
        assert RAW_REPLY not in str(runtime.llm._create.call_args)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_repeated_native_protocol_fails_closed_without_actions(tmp_path):
    runtime = bridge(tmp_path, "emit({'type':'model','request':{'messages':request['messages']}})\nreceive()\n")
    runtime.llm._create.side_effect = [reply(RAW_REPLY), reply(RAW_REPLY)]
    execute = AsyncMock()
    try:
        with pytest.raises(AgentRuntimeError, match="malformed"):
            await run(runtime, execute=execute)
        execute.assert_not_awaited()
        assert runtime.last_run["status"] == "failed" and not runtime.last_run["tools"]
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_protocol_is_hidden_from_terminal_notifications_and_memory(capsys, streamed):
    blob = normal_chat()
    if streamed:
        async def chunks(messages, system):
            for char in RAW_REPLY:
                yield char
        blob.llm.generate_from_messages_stream = chunks
        blob.llm.generate_from_messages.return_value = SimpleNamespace(content="A clean answer.")
    else:
        blob.llm.generate_from_messages.side_effect = [SimpleNamespace(content=RAW_REPLY), SimpleNamespace(content="A clean answer.")]
    answer = await blob.handle_user_message(pb.UserMessage(text="Hello"))
    assert answer == "A clean answer."
    assert not has_tool_protocol(capsys.readouterr().out)
    assert blob.event_dispatcher.broadcast.call_args.args[0].notification.text == answer
    assert "echo done" not in str(list(blob._recent_turns))


@pytest.mark.asyncio
async def test_repeated_classic_protocol_returns_clean_failure():
    blob = normal_chat()
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content=RAW_REPLY)
    answer = await blob.handle_user_message(pb.UserMessage(text="Hello"))
    assert answer == FORMAT_FAILURE and blob.llm.generate_from_messages.await_count == 2


def test_odd_emote_delimiter_is_hidden():
    assert normal_chat()._extract_emote("Hello <|emote>IDLE</emote>") == ("IDLE", "Hello")


def test_internal_tools_require_their_own_user_intent():
    assert requested_system_tools("crazy, is it good?") == set()
    assert "shell_command" in requested_system_tools("Run the command echo hello")
    assert "git_status" in requested_system_tools("Check my git status")


@pytest.mark.asyncio
async def test_followup_reopens_verified_url_when_search_fails_and_clears_on_privacy_reset(tmp_path):
    blob = normal_chat()
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    search = WebSearchSkill(BlobConfig())
    search.async_execute = AsyncMock(side_effect=[web_result({"results": [{"url": "https://example.com/model"}]}),
                                                  SkillResult("Search unavailable", False)])
    read = WebReadSkill()
    read.async_execute = AsyncMock(return_value=web_result({"url": "https://example.com/model",
        "text": "Gemini 4 Argon verified source. " * 10}))
    blob.skill_registry.register(search)
    blob.skill_registry.register(read)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="See the source https://example.com/model")
    await blob.handle_user_message(pb.UserMessage(text="What is Gemini 4 Argon?"))
    answer = await blob.handle_user_message(pb.UserMessage(text="crazy, is it good?"))
    assert "https://example.com/model" in answer and read.async_execute.await_count == 2
    assert blob._last_web_lookup == {"status": "verified", "tools": [
        {"name": "web_search", "success": False}, {"name": "web_read", "success": True}]}
    blob.clear_private_context()
    assert blob._last_product_source is None and blob._last_web_lookup is None
