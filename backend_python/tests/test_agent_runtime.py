"""Exercise the real subprocess boundary and Blob's native-tool authorization."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai.types.chat import ChatCompletion

from blob.agents.hermes import AgentRuntimeError, HermesAgentWrapper
from blob.config import BlobConfig
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.skills.base import SkillResult
from blob.skills.registry import SkillRegistry
from blob.skills.builtin.reminder import ReminderSkill
from blob.ai.prompt_templates import SYSTEM_PROMPT
from blob.ipc import blob_service_pb2 as pb
from test_attachments import orchestrator


def reply(text="A verified reply."):
    return ChatCompletion.model_validate({"id": "test", "object": "chat.completion", "created": 0,
        "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
        "finish_reason": "stop"}]})


def bridge(tmp_path, script, *, controls=None):
    path = tmp_path / "worker.py"
    path.write_text("import json, sys, os, time\nrequest=json.loads(sys.stdin.readline())\n"
        "def emit(frame):\n print(json.dumps(frame),flush=True)\n"
        "def receive():\n return json.loads(sys.stdin.readline())\n" + script)
    config = BlobConfig(nebius_api_key="never-forward-this", agent_timeout_seconds=5)
    runtime = HermesAgentWrapper(config, SimpleNamespace(_create=AsyncMock(return_value=reply())), controls=controls)
    runtime.command = lambda: [sys.executable, str(path)]
    return runtime


async def run(runtime, tools=(), execute=None, event=None):
    return await runtime.run([{"role": "user", "content": "Synthetic request"}], "System", list(tools),
        execute or AsyncMock(return_value=SkillResult("Tool completed.", True, "SUCCESS")), event or AsyncMock())


@pytest.mark.asyncio
async def test_bridge_native_tools_use_blob_provider_and_do_not_forward_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "provider-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "other-secret")
    runtime = bridge(tmp_path, '''
assert 'NEBIUS_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ
assert 'never-forward-this' not in str(request)
emit({'type':'model','id':1,'request':{'model':'attacker-model','messages':[{'role':'user','content':'test'}],'tools':[{'type':'function','function':{'name':'blob_test'}}]}})
response=receive()
assert response['id']==1 and response['result']['choices'][0]['message']['content']=='A verified reply.'
emit({'type':'tool','id':2,'name':'blob_test','args':{'value':'test'}})
assert receive()['result']['success'] is True
emit({'type':'final','answer':'Done.','completed':True})
''')
    execute, event = AsyncMock(return_value=SkillResult("Verified", True, "SUCCESS")), AsyncMock()
    assert await run(runtime, [{"name": "blob_test"}], execute, event) == "Done."
    execute.assert_awaited_once_with("blob_test", {"value": "test"})
    assert runtime.llm._create.call_args.kwargs["model"] == runtime.config.model_name
    assert runtime.last_run["tools"] == [{"name": "blob_test", "success": True}]
    assert [call.args[0] for call in event.await_args_list] == ["model", "tool_start", "tool_complete"]
    assert "test" not in json.dumps(runtime.last_run).replace("blob_test", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", [
    {"type": "tool", "name": "camera", "args": {}},
    {"type": "model", "request": {"messages": [], "tools": [{"function": {"name": "terminal"}}]}},
    {"type": "final", "answer": "Claimed success", "completed": False},
])
async def test_unauthorized_or_incomplete_worker_messages_never_execute(tmp_path, frame):
    runtime = bridge(tmp_path, "emit(" + repr(frame) + ")\ntime.sleep(60)\n")
    execute = AsyncMock()
    with pytest.raises(AgentRuntimeError):
        await run(runtime, execute=execute)
    execute.assert_not_awaited()
    runtime.llm._create.assert_not_awaited()
    assert runtime.last_run["status"] == "failed"


@pytest.mark.asyncio
async def test_cloud_off_prevents_starting_worker(tmp_path):
    controls = PrivacyControls(tmp_path / "private" / "privacy.json")
    controls.update(cloud_enabled=False)
    runtime = bridge(tmp_path, "raise AssertionError('worker must not run')", controls=controls)
    with pytest.raises(PrivacyBlocked):
        await run(runtime)
    assert runtime.last_run["status"] == "blocked"


@pytest.mark.asyncio
async def test_privacy_pause_cancels_the_worker_and_its_child_process(tmp_path):
    controls = PrivacyControls(tmp_path / "private" / "privacy.json")
    marker = tmp_path / "pids"
    runtime = bridge(tmp_path, f'''
import subprocess
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
open({str(marker)!r},'w').write(str(os.getpid())+' '+str(child.pid))
emit({{'type':'progress','phase':'waiting'}})
time.sleep(60)
''', controls=controls)
    async def tracked():
        with controls.operation(cloud=True):
            return await run(runtime)
    task = asyncio.create_task(tracked())
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    controls.update(paused=True)
    controls.cancel_requests()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.last_run["status"] == "cancelled"
    # A killed child may briefly remain a zombie waiting for the host's reaper.
    for pid in marker.read_text().split():
        stat = Path(f"/proc/{pid}/stat")
        try:
            state = stat.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            continue  # The kernel reaped it before or during the read.
        assert state in {"Z", "X"}


@pytest.mark.asyncio
async def test_context_limit_blocks_provider_before_model_call(tmp_path):
    runtime = bridge(tmp_path, "emit({'type':'model','request':{'messages':[{'role':'user','content':'x'*40000}]}})\ntime.sleep(60)")
    with pytest.raises(AgentRuntimeError, match="context limit"):
        await run(runtime)
    runtime.llm._create.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_returns_explicit_error_and_removes_worker_profile(tmp_path):
    marker = tmp_path / "profile"
    runtime = bridge(tmp_path, f"open({str(marker)!r},'w').write(os.environ['BLOB_WORKER_PROFILE'])\n"
        "emit({'type':'model','request':{'messages':[{'role':'user','content':'test'}]}})\ntime.sleep(60)")
    runtime.llm._create.side_effect = RuntimeError("private provider body")
    with pytest.raises(AgentRuntimeError, match="provider failed") as exc:
        await run(runtime)
    assert "private provider body" not in str(exc.value)
    assert not Path(marker.read_text()).exists()


@pytest.mark.asyncio
async def test_timeout_removes_profile_and_does_not_retry_actions(tmp_path):
    marker = tmp_path / "profile"
    runtime = bridge(tmp_path, f"open({str(marker)!r},'w').write(os.environ['BLOB_WORKER_PROFILE'])\ntime.sleep(60)")
    runtime.config.agent_timeout_seconds = 0.2
    with pytest.raises(AgentRuntimeError, match="timed out"):
        await run(runtime)
    assert runtime.last_run["status"] == "timed_out"
    assert not Path(marker.read_text()).exists()


@pytest.mark.asyncio
@pytest.mark.skipif(not Path('.runtime/hermes-venv/bin/python').is_file(), reason="separate Hermes runtime not installed")
async def test_real_hermes_core_roundtrip_uses_native_tool_receipts():
    config = BlobConfig(hermes_source_path=str(Path('.runtime/hermes').absolute()),
                        hermes_python=str(Path('.runtime/hermes-venv/bin/python').absolute()),
                        agent_timeout_seconds=30)
    tool_reply = reply()
    tool_reply.choices[0].message.content = None
    from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
    tool_reply.choices[0].message.tool_calls = [ChatCompletionMessageFunctionToolCall(
        id="call_synthetic", type="function", function={"name":"blob_test", "arguments":'{"value":"synthetic"}'})]
    tool_reply.choices[0].finish_reason = "tool_calls"
    llm = SimpleNamespace(_create=AsyncMock(side_effect=[tool_reply, reply("Verified.")]))
    runtime = HermesAgentWrapper(config, llm)
    tools = [{"name":"blob_test","description":"Check a synthetic value.","parameters":{
        "type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":False}}]
    execute = AsyncMock(return_value=SkillResult("Verified synthetic value.",True,"SUCCESS"))
    assert await run(runtime, tools, execute) == "Verified."
    execute.assert_awaited_once_with("blob_test", {"value":"synthetic"})
    assert runtime.last_run["model_calls"] == 2
    assert any(item["role"]=="tool" for item in llm._create.call_args.kwargs["messages"])


@pytest.mark.asyncio
async def test_native_reminder_receipt_blocks_duplicates_and_unsolicited_changes(tmp_path):
    blob = orchestrator()
    blob.screen_sampler = None
    blob.skill_registry = SkillRegistry(tmp_path / "skills")
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3")
    blob.skill_registry.register(reminder)
    seen = []
    async def candidate(messages, system, tools, execute, event):
        assert "```tool_call" not in system
        assert {tool["name"] for tool in tools} == {"blob_reminder"}
        seen.append(await execute("blob_reminder", {"message": "synthetic", "minutes": 5}))
        seen.append(await execute("blob_reminder", {"message": "duplicate", "minutes": 5}))
        return "Reminder set. <emote>SUCCESS</emote>"
    blob.agent_runtime = SimpleNamespace(run=candidate)
    try:
        await blob._handle_hermes_turn([{"role":"system","content":"System"},{"role":"user","content":"Remind me in 5 minutes"}],
            SYSTEM_PROMPT.replace("{skills}", ""), "Remind me in 5 minutes, then list reminders", "reminder", False)
        assert seen[0].success and not seen[1].success
        assert len(reminder.reminders) == 1
        assert "duplicate" in seen[1].output
        async def unsolicited(messages, system, tools, execute, event):
            denied = await execute("blob_reminder", {"message":"not requested","minutes":1})
            assert not denied.success
            return "Hello."
        blob.agent_runtime.run = unsolicited
        await blob._handle_hermes_turn([{"role":"system","content":"System"},{"role":"user","content":"hi"}], "System", "hi", None, False)
        assert len(reminder.reminders) == 1
    finally:
        await reminder.close()


@pytest.mark.asyncio
async def test_runtime_status_is_local_even_when_paused(tmp_path):
    blob = orchestrator()
    blob.controls = PrivacyControls(tmp_path / "private" / "privacy.json")
    blob.controls.update(paused=True, cloud_enabled=False)
    blob.agent_runtime = SimpleNamespace(last_run={"status":"cancelled"})
    result = json.loads(await blob.handle_user_message(pb.UserMessage(text="/agent")))
    assert result["runtime"] == "hermes" and result["last_run"]["status"] == "cancelled"
    blob.llm.generate_from_messages.assert_not_awaited()


def test_invalid_runtime_configuration_fails_instead_of_silent_fallback():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BlobConfig(agent_runtime="hermse")
    with pytest.raises(AgentRuntimeError, match="not configured"):
        HermesAgentWrapper(BlobConfig(agent_runtime="hermes", hermes_source_path="/missing/hermes-runtime"), None).command()


def test_configured_hermes_runtime_is_selected_on_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOB_AGENT_RUNTIME", "hermes")
    config = BlobConfig.load(str(tmp_path / "missing.yaml"))
    assert config.agent_runtime == "hermes"
