"""Synthetic short follow-ups survive blank or presentation-only completions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.agents.hermes import AgentRuntimeError
from blob.ai.context_budget import prompt_size_bytes
from blob.ai.response_format import EMPTY_REPLY_CORRECTION, visible_reply_text
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from test_agent_runtime import bridge, reply, run
from test_reply_presentation import normal_chat


ECHO_MODEL = """
emit({'type':'model','id':1,'request':{'messages':request['messages'],
    'tools':[{'type':'function','function':tool} for tool in request['tools']]}})
response=receive()
answer=response['result']['choices'][0]['message']['content']
emit({'type':'final','answer':answer,'completed':True})
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [
    None, "", " \n\t", "<emote>HAPPY</emote>", "(THINKING)",
    "<think>Internal draft.</think><emote>IDLE</emote>",
    "<analysis>Unfinished internal draft", "<emote>THINK", "\x1b[31m\x1b[0m",
    "THINKING</emote>", "DEEP_THINKING</emote>", "</emote>", "THINKING</emot",
])
async def test_yes_after_synthetic_offer_repairs_empty_reply_with_context(tmp_path, empty):
    blob = normal_chat()
    blob._remember_recent_turn("I am building a fictional model airship.",
                               "Would you like an assembly checklist?")
    runtime = bridge(tmp_path, ECHO_MODEL)
    runtime.llm._create.side_effect = [reply(empty), reply("Start by sorting the model parts. <emote>HAPPY</emote>")]
    blob.agent_runtime = runtime
    try:
        assert await blob.handle_user_message(pb.UserMessage(text="Yes")) == "Start by sorting the model parts."
        first, repaired = runtime.llm._create.await_args_list
        messages = repaired.kwargs["messages"]
        assert messages[-1]["content"] == "Yes"
        assert {"role": "assistant", "content": "Would you like an assembly checklist?"} in messages
        assert EMPTY_REPLY_CORRECTION in messages[0]["content"]
        assert first.kwargs["messages"][0] != messages[0]
        assert runtime.last_run["model_calls"] == 2
        assert runtime.last_run["empty_reply_retries"] == 1
        assert runtime.last_run["status"] == "completed"
        assert "airship" not in str(runtime.last_run)
        blob.llm.generate_from_messages.assert_not_awaited()
        assert blob._recent_turns[-1]["content"] == "Start by sorting the model parts."
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_hermes_orphan_emote_is_hidden_without_an_extra_model_call(tmp_path, capsys):
    blob = normal_chat()
    runtime = bridge(tmp_path, ECHO_MODEL)
    runtime.llm._create.return_value = reply("Let us start with your example. THINKING</emote>")
    blob.agent_runtime = runtime
    try:
        answer = await blob.handle_user_message(pb.UserMessage(text="Help me plan my project"))
        assert answer == "Let us start with your example."
        runtime.llm._create.assert_awaited_once()
        blob.dispatch_emote.assert_awaited_with("THINKING")
        assert blob.event_dispatcher.broadcast.call_args.args[0].notification.text == answer
        assert blob._recent_turns[-1]["content"] == answer
        output = capsys.readouterr().out
        assert "THINKING" not in output and "</emote>" not in output
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_empty_final_after_completed_tool_repairs_text_without_replaying_action(tmp_path):
    runtime = bridge(tmp_path, """
emit({'type':'tool','id':9,'name':'blob_test','args':{'value':'synthetic'}})
assert receive()['result']['success']
request['messages'] += [
    {'role':'assistant','content':None,'tool_calls':[{'id':'call_test','type':'function',
        'function':{'name':'blob_test','arguments':'{}'}}]},
    {'role':'tool','tool_call_id':'call_test','content':'Verified: action completed once.'}]
""" + ECHO_MODEL)
    runtime.llm._create.side_effect = [reply("<emote>SUCCESS</emote>"), reply("The action completed once.")]
    execute = AsyncMock(return_value=SimpleNamespace(success=True, output="Verified"))
    tools = [{"name": "blob_test", "description": "Synthetic action.", "parameters": {"type": "object"}}]
    try:
        assert await run(runtime, tools, execute) == "The action completed once."
        execute.assert_awaited_once_with("blob_test", {"value": "synthetic"})
        retry = runtime.llm._create.call_args.kwargs
        assert retry["tool_choice"] == "none"
        assert retry["messages"][-1]["role"] == "tool"
        assert "completed once" in retry["messages"][-1]["content"]
        assert runtime.last_run["tools"] == [{"name": "blob_test", "success": True}]
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["<emote>IDLE</emote>", "```tool_call\n{\"tool\":\"blob_test\"}\n```", "native"])
async def test_repeated_empty_or_tool_response_fails_without_actions(tmp_path, invalid):
    runtime = bridge(tmp_path, ECHO_MODEL)
    repaired = reply(invalid)
    if invalid == "native":
        from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
        repaired.choices[0].message.content = None
        repaired.choices[0].message.tool_calls = [ChatCompletionMessageFunctionToolCall(
            id="call_test", type="function", function={"name": "blob_test", "arguments": "{}"})]
    runtime.llm._create.side_effect = [reply("<emote>IDLE</emote>"), repaired]
    execute = AsyncMock()
    with pytest.raises(AgentRuntimeError, match="readable reply"):
        await run(runtime, execute=execute)
    assert runtime.llm._create.await_count == 2
    execute.assert_not_awaited()
    assert runtime.last_run["status"] == "failed"
    assert not runtime.worker_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["calls", "context"])
async def test_repair_obeys_existing_turn_budget(tmp_path, limit):
    runtime = bridge(tmp_path, ECHO_MODEL)
    runtime.llm._create.return_value = reply("<emote>IDLE</emote>")
    if limit == "calls":
        runtime.config.agent_max_iterations = 1
    else:
        runtime.config.max_prompt_bytes = prompt_size_bytes([{"role": "user", "content": "Synthetic request"}])
    with pytest.raises(AgentRuntimeError, match="readable reply|no room"):
        await run(runtime)
    assert runtime.llm._create.await_count == 1
    assert runtime.last_run["model_calls"] == 1


@pytest.mark.asyncio
async def test_cloud_off_before_repair_prevents_second_provider_request(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    runtime = bridge(tmp_path, ECHO_MODEL, controls=controls)
    async def disable_cloud(**kwargs):
        controls.update(cloud_enabled=False)
        return reply("<emote>IDLE</emote>")
    runtime.llm._create.side_effect = disable_cloud
    with pytest.raises(PrivacyBlocked):
        await run(runtime)
    assert runtime.llm._create.await_count == 1
    assert runtime.last_run["status"] == "blocked"


@pytest.mark.asyncio
async def test_cancelling_repair_stops_worker_without_replaying_tools(tmp_path):
    runtime = bridge(tmp_path, ECHO_MODEL)
    started = asyncio.Event()
    async def complete(**kwargs):
        if EMPTY_REPLY_CORRECTION not in str(kwargs["messages"]):
            return reply("<emote>IDLE</emote>")
        started.set()
        await asyncio.Event().wait()
    runtime.llm._create.side_effect = complete
    task = asyncio.create_task(run(runtime))
    try:
        await asyncio.wait_for(started.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime.last_run["status"] == "cancelled"
        assert not runtime.worker_ready and runtime._profile is None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.close()


def test_visible_reply_preserves_real_text_next_to_controls():
    assert visible_reply_text("<think>Hidden draft.</think>Yes, let's start. <emote>HAPPY</emote>") == "Yes, let's start."
