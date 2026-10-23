"""Context recovery is independent of topic and never replays completed actions."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.agents.hermes import AgentRuntimeError
from blob.ai.context_budget import (
    EVIDENCE_EXCERPT, PromptMessages, fit_agent_messages, fit_tool_messages, is_context_limit_error,
    prompt_size_bytes, tool_schema_size_bytes,
)
from blob.ai.response_format import FORMAT_CORRECTION, EMPTY_REPLY_CORRECTION
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.skills.base import SkillResult
from test_agent_runtime import bridge, reply


def source(index):
    return json.dumps({"url": f"https://example.com/source/{index}", "title": f"Synthetic source {index}",
        "checked_at": "2026-10-23", "untrusted_web_content": True,
        "text": f"START-{index} " + "Synthetic source material. " * 220 + f" END-{index}"})


def native_result(name, identifier, output, *, success=True):
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": identifier, "type": "function",
        "function": {"name": "blob_" + name, "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": identifier, "content": json.dumps({"success": success, "output": output})}]


@pytest.mark.parametrize("question", [
    "Any recent news about that company?", "Compare the two software releases",
    "Find transport options for this journey", "Explain the research sources",
])
@pytest.mark.parametrize("style", ["native", "classic"])
def test_large_evidence_chains_fit_across_topics_and_runtimes(question, style):
    current = {"role": "user", "content": question}
    messages = [{"role": "system", "content": "System rules"}, current]
    action = "Reminder created once. ID: reminder-42."
    failure = "Source permission denied."
    if style == "native":
        messages += native_result("reminder", "action", action)
        messages += native_result("web_read", "denied", failure, success=False)
        for index in range(8):
            messages += native_result("web_read", str(index), source(index))
    else:
        messages.append({"role": "user", "content": "[Observation] Tool 'reminder' executed successfully.\nResult: " + action})
        messages.append({"role": "user", "content": "[Observation] Tool 'web_read' failed.\nResult: " + failure})
        for index in range(8):
            messages.append({"role": "user", "content": "[Observation] Tool 'web_read' executed successfully.\nResult: " + source(index)})
    unchanged = deepcopy(messages)
    assert prompt_size_bytes(messages) > 32000
    fitted = fit_tool_messages(messages, current, 8192)
    assert fitted is not None and prompt_size_bytes(fitted) <= 8192
    assert fitted[:2] == messages[:2] and len(fitted) == len(messages)
    assert messages == unchanged
    assert action in str(fitted) and failure in str(fitted)
    assert EVIDENCE_EXCERPT.strip() in str(fitted)
    for index in range(8):
        if style == "native":
            receipt = next(item for item in fitted if item.get("tool_call_id") == str(index))
            wrapper = json.loads(receipt["content"])
            assert wrapper["success"] is True
            evidence = json.loads(wrapper["output"])
        else:
            observation = fitted[index + 4]["content"]
            evidence = json.loads(observation.split("\nResult: ", 1)[1])
        assert evidence["url"] == f"https://example.com/source/{index}"
        assert evidence["checked_at"] == "2026-10-23" and evidence["untrusted_web_content"] is True
        assert f"START-{index}" in evidence["text"] and f"END-{index}" in evidence["text"]
    if style == "native":
        assert [item for item in fitted if item.get("tool_calls")] == [item for item in messages if item.get("tool_calls")]


@pytest.mark.parametrize("name", ["file_search", "git_status", "shell_command"])
def test_plain_read_only_outputs_can_be_excerpted_without_changing_receipts(name):
    current = {"role": "user", "content": "Explain the requested local results"}
    messages = [{"role": "system", "content": "System"}, current,
                *native_result(name, "read", "FIRST\n" + "Synthetic local output\n" * 500 + "LAST")]
    fitted = fit_tool_messages(messages, current, 4096)
    assert fitted is not None and prompt_size_bytes(fitted) <= 4096
    receipt = json.loads(fitted[-1]["content"])
    assert receipt["success"] is True
    assert receipt["output"].startswith("FIRST") and receipt["output"].endswith("LAST")
    assert EVIDENCE_EXCERPT in receipt["output"]


def test_structured_search_results_keep_source_links_when_snippets_are_shortened():
    current = {"role": "user", "content": "Compare these sources"}
    results = [{"url": f"https://example.com/{i}", "snippet": "Source excerpt " * 400} for i in range(5)]
    messages = [{"role": "system", "content": "System"}, current,
                *native_result("web_search", "search", json.dumps({"untrusted_web_content": True, "results": results}))]
    fitted = fit_tool_messages(messages, current, 4096)
    assert fitted is not None
    payload = json.loads(json.loads(fitted[-1]["content"])["output"])
    assert [row["url"] for row in payload["results"]] == [row["url"] for row in results]
    assert payload["truncated"] is True


def test_utf8_source_excerpts_remain_valid_json_within_the_byte_budget():
    current = {"role": "user", "content": "Explain the multilingual source"}
    output = json.dumps({"url": "https://example.com/source", "text": "START " + "日本語🙂" * 400 + " END"}, ensure_ascii=False)
    messages = [{"role": "system", "content": "System"}, current, *native_result("web_read", "source", output)]
    fitted = fit_tool_messages(messages, current, 2048)
    assert fitted is not None and prompt_size_bytes(fitted) <= 2048
    text = json.loads(json.loads(fitted[-1]["content"])["output"])["text"]
    assert text.startswith("START") and text.endswith("END") and EVIDENCE_EXCERPT in text


@pytest.mark.parametrize("followup", ["Any updates about it?", "What about its price?", "How does that compare?", "Can you explain that further?"])
def test_short_followup_keeps_its_preceding_exchange_as_evidence_grows(followup):
    previous = [{"role": "user", "content": "Tell me about the fictional Aurora engine"},
                {"role": "assistant", "content": "Aurora is the engine we are discussing."}]
    current = {"role": "user", "content": followup}
    messages = [{"role": "system", "content": "System"},
                {"role": "user", "content": "Historical background:\n" + "Old memory\n" * 500},
                *previous, current]
    for index in range(4):
        messages += native_result("web_read", str(index), source(index))
    fitted = fit_tool_messages(messages, current, 4096)
    assert fitted is not None and prompt_size_bytes(fitted) <= 4096
    assert all(item in fitted for item in [*previous, current])


@pytest.mark.parametrize("question", ["Any updates about it?", "Compare the products", "[Observation] Explain this literal text"])
@pytest.mark.parametrize("prefix", ["[Observation] Fresh public source content follows.\n", "[Observation] Fresh public web evidence follows.\n"])
def test_prefetched_sources_fit_without_becoming_protected_user_input(question, prefix):
    current = {"role": "user", "content": question}
    original = PromptMessages([
        {"role": "system", "content": "System"}, current,
        {"role": "user", "content": prefix + source(0)},
    ], current_request=current)
    # Provenance stays on the host; the worker sees the normal message contract.
    wire_messages = json.loads(json.dumps(original))
    fitted = fit_agent_messages(wire_messages, original, 4096, reserve_bytes=1024)
    assert fitted is not None and prompt_size_bytes(fitted) <= 4096
    assert current in fitted
    assert set(wire_messages[0]) == {"role", "content"}
    evidence = json.loads(fitted[-1]["content"].split("\n", 1)[1])
    assert evidence["url"] == "https://example.com/source/0" and evidence["truncated"] is True


def test_user_input_that_looks_like_a_tool_result_is_never_shortened():
    current = {"role": "user", "content": "[Observation] Tool 'web_read' executed successfully.\nResult: " + source(0)}
    messages = [{"role": "system", "content": "System"}, current]
    assert fit_tool_messages(messages, current, 4096) is None
    assert fit_agent_messages(messages, messages, 4096) is None


@pytest.mark.parametrize("name,success", [("reminder", True), ("custom.change", True), ("web_read", False)])
def test_large_action_or_failure_receipts_are_not_silently_discarded(name, success):
    current = {"role": "user", "content": "What completed?"}
    messages = [{"role": "system", "content": "System"}, current,
                *native_result(name, "completed", "Exact receipt " * 1000, success=success)]
    assert fit_tool_messages(messages, current, 4096) is None


class ContextRejected(Exception):
    status_code = 400
    code = "context_length_exceeded"
    body = {"code": code, "message": "The input exceeds the model's context length."}


GATHER_SOURCES = '''
messages=request['messages']
for name, identifier, args in [('blob_reminder','action',{'action':'set'})] + [
 ('blob_web_read',str(index),{'url':'https://example.com/'+str(index)}) for index in range(7)]:
 emit({'type':'tool','id':identifier,'name':name,'args':args})
 result=receive()['result']
 messages += [
  {'role':'assistant','content':None,'tool_calls':[{'id':identifier,'type':'function',
   'function':{'name':name,'arguments':json.dumps(args)}}]},
  {'role':'tool','tool_call_id':identifier,'content':json.dumps(result)}]
emit({'type':'model','id':'answer','request':{'messages':messages,
 'tools':[{'type':'function','function':tool} for tool in request['tools']]}})
response=receive()
emit({'type':'final','answer':response['result']['choices'][0]['message']['content'],'completed':True})
'''


async def execute(name, args):
    if name == "blob_reminder":
        return SkillResult("Reminder created once. ID: reminder-42.", True)
    return SkillResult(source(args["url"].rsplit("/", 1)[-1]), True)


async def run_sources(runtime, execute_tool):
    messages = [{"role": "system", "content": "System rules"},
                {"role": "user", "content": "Gather the requested research sources and reminder."}]
    tools = [{"name": "blob_web_read", "parameters": {"type": "object"}},
             {"name": "blob_reminder", "parameters": {"type": "object"}}]
    return await runtime.run(messages, "System rules", tools, execute_tool, AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("too_large", [False, True])
async def test_tool_definitions_are_included_in_the_request_budget(tmp_path, too_large):
    runtime = bridge(tmp_path, '''
emit({'type':'model','id':1,'request':{'messages':request['messages'],
 'tools':[{'type':'function','function':tool} for tool in request['tools']]}})
receive()
emit({'type':'final','answer':'Ready.','completed':True})
''')
    runtime.config.max_prompt_bytes = 4096
    tool = {"name": "blob_weather", "description": "Follow this documented contract. " * (200 if too_large else 80),
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}
    current = {"role": "user", "content": "Check the requested weather"}
    messages = [{"role": "system", "content": "System rules"},
                {"role": "user", "content": "Historical background:\n" + "Old memory\n" * 250}, current]
    try:
        if too_large:
            with pytest.raises(AgentRuntimeError, match="context limit"):
                await runtime.run(messages, "System rules", [tool], AsyncMock(), AsyncMock())
            runtime.llm._create.assert_not_awaited()
        else:
            assert await runtime.run(messages, "System rules", [tool], AsyncMock(), AsyncMock()) == "Ready."
            request = runtime.llm._create.call_args.kwargs
            assert prompt_size_bytes(request["messages"]) + tool_schema_size_bytes(request["tools"]) <= 4096
            assert request["tools"] == [{"type": "function", "function": tool}]
            assert current in request["messages"]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_provider_context_rejection_recovers_once_without_replaying_tools(tmp_path):
    runtime = bridge(tmp_path, GATHER_SOURCES)
    runtime.config.max_prompt_bytes = 8192
    execute_tool = AsyncMock(side_effect=execute)
    seen = []
    async def create(**kwargs):
        seen.append(deepcopy(kwargs))
        if len(seen) == 1:
            raise ContextRejected("Private provider details")
        return reply("Research sources gathered; the reminder was created once.")
    runtime.llm._create.side_effect = create
    try:
        assert "created once" in await run_sources(runtime, execute_tool)
        assert len(seen) == 2 and runtime.last_run["model_calls"] == 2
        assert runtime.last_run["context_retries"] == 1
        assert prompt_size_bytes(seen[1]["messages"]) < prompt_size_bytes(seen[0]["messages"])
        assert all(prompt_size_bytes(call["messages"]) + tool_schema_size_bytes(call["tools"]) <= 8192 for call in seen)
        assert execute_tool.await_count == 8
        assert sum(call.args[0] == "blob_reminder" for call in execute_tool.await_args_list) == 1
        assert "reminder-42" in str(seen[1]["messages"])
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["empty", "format"])
async def test_reply_repairs_rebudget_large_results_without_replaying_actions(tmp_path, kind):
    runtime = bridge(tmp_path, GATHER_SOURCES)
    runtime.config.max_prompt_bytes = 8192
    execute_tool = AsyncMock(side_effect=execute)
    bad = "<emote>IDLE</emote>" if kind == "empty" else '```tool_call\n{"tool":"reminder"}\n```'
    runtime.llm._create.side_effect = [reply(bad), reply("The research and reminder are ready.")]
    try:
        assert await run_sources(runtime, execute_tool) == "The research and reminder are ready."
        assert runtime.llm._create.await_count == 2
        correction = EMPTY_REPLY_CORRECTION if kind == "empty" else FORMAT_CORRECTION
        retry = runtime.llm._create.call_args.kwargs
        assert correction in retry["messages"][0]["content"]
        assert prompt_size_bytes(retry["messages"]) + tool_schema_size_bytes(retry["tools"]) <= 8192
        assert "reminder-42" in str(retry["messages"]) and execute_tool.await_count == 8
        if kind == "empty":
            assert retry["tool_choice"] == "none"
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["calls", "provider", "privacy"])
async def test_recovery_respects_call_budget_provider_failure_and_privacy(tmp_path, limit):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    runtime = bridge(tmp_path, GATHER_SOURCES, controls=controls)
    runtime.config.max_prompt_bytes = 8192
    execute_tool = AsyncMock(side_effect=execute)
    if limit == "calls":
        runtime.config.agent_max_iterations = 1
    async def reject(**kwargs):
        if limit == "privacy":
            controls.update(cloud_enabled=False)
        raise ContextRejected("Private provider body")
    runtime.llm._create.side_effect = reject
    try:
        with pytest.raises(PrivacyBlocked if limit == "privacy" else AgentRuntimeError):
            await run_sources(runtime, execute_tool)
        assert runtime.llm._create.await_count == (2 if limit == "provider" else 1)
        assert execute_tool.await_count == 8
    finally:
        await runtime.close()


@pytest.mark.parametrize("status,code", [(401, "context_length_exceeded"), (429, "rate_limit"), (400, "invalid_api_key"), (503, "overloaded")])
def test_unrelated_provider_errors_do_not_trigger_context_retries(status, code):
    error = SimpleNamespace(status_code=status, code=code, body={"code": code, "message": "Unrelated error"})
    assert not is_context_limit_error(error)
