"""Natural travel enquiries use real tools, never printed function-call JSON."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest

from blob.agents.hermes import AgentRuntimeError
from blob.ai.orchestrator import BlobOrchestrator
from blob.ai.response_format import FORMAT_FAILURE, has_tool_protocol
from blob.ai.tool_policy import ModelToolPolicy
from blob.ai.web_grounding import live_travel_request
from blob.ipc import blob_service_pb2 as pb
from blob.skills.builtin.web import web_result
from test_agent_runtime import bridge, reply, run
from test_reply_presentation import normal_chat
from test_tool_policy import web_registry


REQUEST = "could you check if there are any flights available from banglore to delhi on 24th oct. Any time works"
QUERY = "flights from Bangalore to Delhi October 24 2026"
RAW = json.dumps({"query": QUERY}) + "\n\n" + json.dumps({"tool": "web_search", "arguments": {"query": QUERY}})
SOURCE = "https://airline.example/enquiry"


@pytest.mark.parametrize("text", [REQUEST, "Find flights from Bengaluru to Delhi on October 24",
    "Any flights from Bangalore to Delhi on Oct 24?", "Are there seats available on train 12345?",
    "Can u check hotels in Delhi for 24 October?", "Look up airfares from BLR to DEL"])
def test_travel_enquiries_authorize_live_lookup(text):
    assert live_travel_request(text)
    policy = ModelToolPolicy.for_request(text, SimpleNamespace(skills={}))
    assert policy.query == text
    assert {"web_search", "web_read", "browser"} <= policy.allowed


@pytest.mark.parametrize("text", ["I found flights from Bangalore to Delhi", "I booked my flights yesterday",
    "Write an email about flight availability", "What do you remember about my flight?",
    "Don't check flights", "Explain how planes fly", "Check whether my saved file is available",
    "Find my saved flight tickets", "Check the flight ticket document"])
def test_nonlookup_requests_do_not_grant_travel_tools(text):
    assert not live_travel_request(text)


@pytest.mark.parametrize("text", [RAW, json.dumps({"tool": "web_search", "arguments": {"query": QUERY}}),
    'Searching now. {"tool":"web_search","args":{"query":"x"}}',
    '{"tool":"web_search","arguments":', '{"tool_calls":[]}', '<tool_call>{"tool":"web_search"}</tool_call>'])
def test_printed_tool_requests_are_detected(text):
    assert has_tool_protocol(text)


def test_parameters_are_rejected_only_for_live_lookups_and_regular_json_is_preserved():
    parameters = json.dumps({"query": QUERY})
    assert not has_tool_protocol(parameters)
    assert has_tool_protocol(parameters, search_arguments=True)
    assert not has_tool_protocol('{"departure":"BLR","arrival":"DEL"}', search_arguments=True)
    assert not has_tool_protocol('{"tool":"hammer","weight":2}')
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    assert instance._parse_tool_call(RAW) == (None, None)
    assert instance._parse_tool_call(json.dumps({"tool": "web_search", "arguments": {"query": QUERY}})) == (None, None)
    assert instance._parse_tool_call('{"tool":"web_search","args":{"query":"x"}}') == ("web_search", {"query": "x"})


@pytest.mark.asyncio
@pytest.mark.parametrize("streamed", [False, True])
async def test_reported_flight_request_searches_and_repairs_json_before_display(tmp_path, capsys, streamed):
    blob = normal_chat()
    blob.skill_registry, search, read, _ = web_registry(tmp_path)
    search.async_execute.return_value = web_result({"results": [{"url": SOURCE}]})
    read.async_execute.return_value = web_result({"url": SOURCE, "text": "Public flight enquiry page, not verified seat inventory."})
    valid_call = json.dumps({"tool": "web_search", "args": {"query": QUERY}})
    answer = "I found an enquiry page, but couldn't confirm live inventory. Source: " + SOURCE
    if streamed:
        completions = iter([RAW, answer])
        async def chunks(messages, system):
            for character in next(completions):
                yield character
        blob.llm.generate_from_messages_stream = chunks
        blob.llm.generate_from_messages.return_value = SimpleNamespace(content=valid_call)
    else:
        blob.llm.generate_from_messages.side_effect = [SimpleNamespace(content=RAW),
            SimpleNamespace(content=valid_call), SimpleNamespace(content=answer)]
    result = await blob.handle_user_message(pb.UserMessage(text=REQUEST))
    assert result == answer
    assert search.async_execute.await_count == 2  # Preflight and the repaired, authorized call.
    assert all(call.args[0]["query"] == REQUEST for call in search.async_execute.await_args_list)
    read.async_execute.assert_awaited_once()
    output = capsys.readouterr().out
    assert '"tool"' not in output and '"query"' not in output
    assert '"arguments"' not in str(list(blob._recent_turns))


@pytest.mark.asyncio
async def test_repeated_malformed_flight_response_returns_plain_error(tmp_path, capsys):
    blob = normal_chat()
    blob.skill_registry, *_ = web_registry(tmp_path)
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content=RAW)
    assert await blob.handle_user_message(pb.UserMessage(text=REQUEST)) == FORMAT_FAILURE
    assert blob.llm.generate_from_messages.await_count == 2
    assert '"arguments"' not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_streamed_json_after_prose_is_withheld_until_validated(capsys):
    blob = normal_chat()
    async def chunks(messages, system):
        for character in "I'll check. " + RAW:
            yield character
    blob.llm.generate_from_messages_stream = chunks
    blob.llm.generate_from_messages.return_value = SimpleNamespace(content="How can I help?")
    assert await blob.handle_user_message(pb.UserMessage(text="Hello")) == "How can I help?"
    assert '"query"' not in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [RAW, json.dumps({"query": QUERY})])
async def test_native_final_guard_keeps_json_out_of_chat(tmp_path, malformed):
    blob = normal_chat()
    blob.skill_registry, *_ = web_registry(tmp_path)
    blob.agent_runtime = SimpleNamespace(run=AsyncMock(return_value=malformed), last_run={})
    assert await blob.handle_user_message(pb.UserMessage(text=REQUEST)) == FORMAT_FAILURE


@pytest.mark.asyncio
async def test_native_flight_enquiry_gets_web_tools_and_checked_evidence(tmp_path):
    blob = normal_chat()
    blob.skill_registry, search, read, _ = web_registry(tmp_path)
    async def answer(messages, system, tools, execute, event):
        assert {tool["name"] for tool in tools} == {"blob_web_search", "blob_web_read", "blob_browser"}
        search.async_execute.assert_awaited_once()
        read.async_execute.assert_awaited_once()
        assert "Fresh public source" in messages[-1]["content"]
        return "Checked source: https://example.com/python"
    blob.agent_runtime = SimpleNamespace(run=answer, last_run={})
    assert "Checked source" in await blob.handle_user_message(pb.UserMessage(text=REQUEST))


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [RAW, json.dumps({"query": QUERY})])
async def test_native_transport_retries_printed_json_through_real_tool_interface(tmp_path, malformed):
    runtime = bridge(tmp_path, """
emit({'type':'model','id':1,'request':{'messages':request['messages'],'tools':[{'type':'function','function':{'name':'blob_web_search'}}]}})
response=receive()['result']['choices'][0]['message']
assert response['content'] is None
call=response['tool_calls'][0]['function']
emit({'type':'tool','id':2,'name':call['name'],'args':json.loads(call['arguments'])})
assert receive()['result']['success']
emit({'type':'final','answer':'Search completed through the actual tool.','completed':True})
""")
    native = reply().model_dump()
    native['choices'][0]['message'].update(content=None, tool_calls=[{'id':'call1','type':'function',
        'function':{'name':'blob_web_search','arguments':json.dumps({'query':QUERY})}}])
    runtime.llm._create.side_effect = [reply(malformed), type(reply()).model_validate(native)]
    execute = AsyncMock(return_value=SimpleNamespace(success=True, output="Checked source"))
    try:
        assert "actual tool" in await run(runtime, tools=[{'name':'blob_web_search'}], execute=execute)
        execute.assert_awaited_once_with('blob_web_search', {'query':QUERY})
        assert runtime.last_run['format_retries'] == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_native_repeated_printed_json_never_executes_generated_actions(tmp_path):
    runtime = bridge(tmp_path, "emit({'type':'model','request':{'messages':request['messages']}})\nreceive()\n")
    runtime.llm._create.side_effect = [reply(RAW), reply(RAW)]
    execute = AsyncMock()
    try:
        with pytest.raises(AgentRuntimeError, match="malformed"):
            await run(runtime, execute=execute)
        execute.assert_not_awaited()
    finally:
        await runtime.close()
