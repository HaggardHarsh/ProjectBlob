"""User-oriented checks from the autonomous conversation audit run in every CI."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ai.tool_policy import ModelToolPolicy
from blob.ai.llm_engine import NebiusEngine
from blob.ai.tool_policy import MODEL_POLICY
from blob.evals.conversation_audit import boundary_checks
from blob.ipc import blob_service_pb2 as pb
from test_reply_presentation import normal_chat
from test_tool_policy import web_registry
from test_agent_runtime import reply


@pytest.mark.parametrize("case", boundary_checks(), ids=lambda c: c["case"])
def test_audited_request_and_reply_boundaries(case):
    assert case["passed"], case


@pytest.mark.parametrize("text", ["What is photosynthesis?", "How much rain falls in Delhi?",
    "Tell me a joke about it", "Tell me my saved account number again"])
def test_unrelated_followup_does_not_inherit_public_authority(text):
    registry = SimpleNamespace(skills={})
    previous = ModelToolPolicy.for_request("Check flights to Delhi", registry)
    assert not ModelToolPolicy.for_request(text, registry, previous=previous).query


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_declined_web_lookup_never_contacts_tools_even_for_known_ai_product(tmp_path, native):
    blob = normal_chat()
    blob.skill_registry, search, read, browser = web_registry(tmp_path)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="A layover is a stop between connecting flights.")
    if native:
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value="A layover is a stop between connecting flights."), last_run={})
    answer = await blob.handle_user_message(pb.UserMessage(text="Don't search the web for Gemini again. Explain a layover."))
    assert "layover" in answer
    for tool in (search, read, browser):
        tool.async_execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_screen_shield_keeps_recent_corrections_and_archives_each_turn():
    blob = normal_chat()
    blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(is_capture_blocked=lambda: True))
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="I'll call the project Cobalt.")
    correction = "For this conversation call the test project Cobalt instead"
    await blob.handle_user_message(pb.UserMessage(text=correction))

    async def followup(messages, system):
        assert {"role": "user", "content": correction} in messages
        assert any(m["role"] == "assistant" and "Cobalt" in m["content"] for m in messages)
        return SimpleNamespace(content="Cobalt.")

    blob.llm.generate_from_messages.side_effect = followup
    assert await blob.handle_user_message(pb.UserMessage(text="What is the test project's name now?")) == "Cobalt."
    assert blob.episodic.add_episode.call_count == 2
    blob.episodic.add_episode.assert_any_call(correction, "I'll call the project Cobalt.")
    blob.episodic.add_episode.assert_any_call("What is the test project's name now?", "Cobalt.")


@pytest.mark.parametrize("opening,closing", [("【", "】"), ("“", "”"), ("[source](", ")"), ("", "."), ("\u200b", "\u200b")])
def test_real_model_citation_wrappers_are_accepted(tmp_path, opening, closing):
    from blob.skills.builtin.web import web_result
    registry, *_ = web_registry(tmp_path)
    policy = ModelToolPolicy.for_request("Check the web for the latest release", registry)
    url = "https://example.com/release"
    policy.observe("web_read", web_result({"url": url, "text": "Version 5.2 is stable."}))
    answer = "Version 5.2 is stable " + opening + url + closing
    assert policy.grounded_answer(answer) == answer


def test_invisible_characters_cannot_disguise_an_unverified_citation(tmp_path):
    from blob.skills.builtin.web import web_result
    registry, *_ = web_registry(tmp_path)
    policy = ModelToolPolicy.for_request("Check the web for a release", registry)
    policy.observe("web_read", web_result({"url": "https://example.com", "text": "Source content"}))
    answer = "See https://example.com\u200b.evil.example"
    checked = policy.grounded_answer(answer)
    assert checked != answer and ".evil.example" not in checked
    assert "https://example.com" in checked


def native_reply(*names, content=None, arguments='{"query":"model-chosen query"}'):
    data = reply().model_dump()
    data["choices"][0]["message"].update(content=content, tool_calls=[
        {"id": f"call-{index}", "type": "function", "function": {"name": name, "arguments": arguments}}
        for index, name in enumerate(names)])
    return type(reply()).model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_classic_uses_structured_tool_channel_and_host_authority(tmp_path, streamed):
    blob = normal_chat()
    registry, search, *_ = web_registry(tmp_path)
    blob.skill_registry = registry
    engine = NebiusEngine("synthetic-audit-key", "https://api.invalid/v1", "test-model", tool_registry=registry)
    engine._create = AsyncMock(side_effect=[native_reply("blob_web_search", content="Fictional success text"),
        reply("Checked source: https://example.com/python")])
    blob.llm = engine
    blob._streaming_disabled = not streamed
    text = "Check the web for the current Python release"
    assert "Checked source" in await blob.handle_user_message(pb.UserMessage(text=text))
    assert search.async_execute.await_count == 2
    assert all(call.args[0]["query"] == text for call in search.async_execute.await_args_list)
    request = engine._create.call_args_list[0].kwargs
    assert request["parallel_tool_calls"] is False
    assert {tool["function"]["name"] for tool in request["tools"]} == {"blob_web_search", "blob_web_read", "blob_browser"}
    assert "### How to Call a Tool" not in request["messages"][0]["content"]
    assert "Fictional success" not in str(blob._recent_turns)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [native_reply("blob_web_search", "blob_web_read"),
    native_reply("blob_shell_command"), native_reply("blob_web_search", arguments="not JSON")])
async def test_invalid_structured_requests_never_execute(tmp_path, response):
    from blob.ai.response_format import FORMAT_FAILURE
    blob = normal_chat()
    registry, search, *_ = web_registry(tmp_path)
    blob.skill_registry = registry
    blob.llm = NebiusEngine("synthetic-audit-key", "https://api.invalid/v1", "test-model", tool_registry=registry)
    blob.llm._create = AsyncMock(return_value=response)
    assert await blob.handle_user_message(pb.UserMessage(text="Check the web for Python")) == FORMAT_FAILURE
    assert search.async_execute.await_count == 1  # Only the host's preflight.


@pytest.mark.asyncio
async def test_changed_travel_date_searches_again_instead_of_reusing_previous_page(tmp_path):
    blob = normal_chat()
    blob.skill_registry, search, read, _ = web_registry(tmp_path)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="Checked source: https://example.com/python")
    await blob.handle_user_message(pb.UserMessage(text="Check flights to Delhi on 24 October"))
    await blob.handle_user_message(pb.UserMessage(text="What about 25 October instead?"))
    assert search.async_execute.await_count == read.async_execute.await_count == 2
    assert "25 October" in search.async_execute.call_args.args[0]["query"]


def test_classic_exposes_no_native_tools_without_request_scope(tmp_path):
    registry, *_ = web_registry(tmp_path)
    engine = NebiusEngine("synthetic-audit-key", "https://api.invalid/v1", "test-model", tool_registry=registry)
    assert engine._request_tools() == ([], {})
    token = MODEL_POLICY.set(ModelToolPolicy.for_request("Hello", registry))
    try:
        assert engine._request_tools() == ([], {})
    finally:
        MODEL_POLICY.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_reserved_model_tokens_never_reach_terminal_or_memory(capsys, streamed):
    blob = normal_chat()
    raw = "Cobalt.<|reserved_token_163786|><|end|><|start|><|endoftext|>"
    blob.llm.generate_from_messages = AsyncMock(side_effect=[SimpleNamespace(content=raw), SimpleNamespace(content="Cobalt.")])
    if streamed:
        async def stream(messages, system):
            for character in raw:
                yield character
        blob.llm.generate_from_messages_stream = stream
        blob.llm.generate_from_messages.side_effect = [SimpleNamespace(content="Cobalt.")]
    assert await blob.handle_user_message(pb.UserMessage(text="What is the test project's name now?")) == "Cobalt."
    assert "reserved_token" not in capsys.readouterr().out
    assert "reserved_token" not in str(blob._recent_turns)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_missing_citation_is_repaired_once_without_any_more_tools(tmp_path, native):
    blob = normal_chat()
    registry, search, read, _ = web_registry(tmp_path)
    blob.skill_registry = registry
    blob.llm = NebiusEngine("synthetic-audit-key", "https://api.invalid/v1", "test-model", tool_registry=registry)
    blob.llm._create = AsyncMock(side_effect=([reply("Checked current source.")] if not native else []) +
        [reply("Checked current source: https://example.com/python")])
    if native:
        blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value="Checked current source."), last_run={})
    answer = await blob.handle_user_message(pb.UserMessage(text="Check the web for the current Python release"))
    assert answer == "Checked current source: https://example.com/python"
    search.async_execute.assert_awaited_once()
    read.async_execute.assert_awaited_once()
    repair = blob.llm._create.call_args.kwargs
    assert "tools" not in repair
    assert "exact URL" in str(repair["messages"])


@pytest.mark.asyncio
async def test_citation_repair_never_executes_returned_actions_or_uses_invented_urls(tmp_path):
    blob = normal_chat()
    registry, search, read, browser = web_registry(tmp_path)
    blob.skill_registry = registry
    blob.llm = NebiusEngine("synthetic-audit-key", "https://api.invalid/v1", "test-model", tool_registry=registry)
    blob.llm._create = AsyncMock(side_effect=[reply("The source has a release."), native_reply("blob_browser")])
    answer = await blob.handle_user_message(pb.UserMessage(text="Check the web for the current Python release"))
    assert "properly sourced" in answer
    search.async_execute.assert_awaited_once()
    read.async_execute.assert_awaited_once()
    browser.async_execute.assert_not_awaited()
    assert "tool_calls" not in answer


@pytest.mark.asyncio
async def test_citation_repair_respects_native_model_budget(tmp_path):
    blob = normal_chat()
    blob.skill_registry, *_ = web_registry(tmp_path)
    blob.config.agent_max_iterations = 1
    blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value="Current source checked."), last_run={"model_calls": 1})
    answer = await blob.handle_user_message(pb.UserMessage(text="Check the web for the current Python release"))
    assert "properly sourced" in answer
    blob.llm.generate_from_messages.assert_not_awaited()
    assert blob.agent_runtime.last_run["model_calls"] == 1
