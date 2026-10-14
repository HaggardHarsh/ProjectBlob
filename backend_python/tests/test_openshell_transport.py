"""Simulate the OpenShell CLI boundary, including independent remote processes."""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.agents.hermes import AgentRuntimeError, HermesAgentWrapper
from blob.config import BlobConfig
from test_agent_runtime import reply, run


@pytest.fixture
def openshell(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "must-stay-on-host")
    monkeypatch.setenv("OPENAI_API_KEY", "also-host-only")
    worker = tmp_path / "worker.py"
    worker.write_text('''import json,sys,time,os
assert 'NEBIUS_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ
json.loads(sys.stdin.readline())
print(json.dumps({'type':'ready'}),flush=True)
for line in sys.stdin:
 request=json.loads(line)
 print(json.dumps({'type':'model','id':1,'request':{'messages':request['messages']}}),flush=True)
 json.loads(sys.stdin.readline())
 print(json.dumps({'type':'final','answer':'Verified.','completed':True}),flush=True)
''')
    cli = tmp_path / "openshell"
    cli.write_text(f'#!{sys.executable}\n' + r'''import json,os,sys,subprocess,signal
from pathlib import Path
assert 'NEBIUS_API_KEY' not in os.environ and 'OPENAI_API_KEY' not in os.environ
root=Path(os.environ['XDG_CONFIG_HOME'])
args=sys.argv[1:]
with (root/'events').open('a') as log:
 log.write(json.dumps(args)+'\n')
kind=args[args.index('sandbox')+1]
if kind=='create':
 print('Created')
elif kind=='exec':
 child=subprocess.Popen([sys.executable,str(root/'worker.py')],start_new_session=True)
 (root/'pid').write_text(str(child.pid))
 sys.exit(child.wait())
elif kind=='stop':
 if (root/'fail-cleanup').exists():
  sys.exit(1)
 if (root/'pid').exists():
  try:
   os.killpg(int((root/'pid').read_text()),signal.SIGKILL)
  except ProcessLookupError:
   pass
 print('Stopped')
elif kind=='delete':
 name=args[-1]
 if (root/'fail-cleanup').exists():
  print(f'Sandbox {name} deletion accepted; cleanup is pending')
 else:
  print(f'Deleted sandbox {name}')
''')
    cli.chmod(0o700)
    config = BlobConfig(hermes_transport="openshell", openshell_cli=str(cli),
                        openshell_config_dir=str(tmp_path), agent_timeout_seconds=5)
    runtime = HermesAgentWrapper(config, SimpleNamespace(_create=AsyncMock(return_value=reply())))
    return runtime, tmp_path


def events(root):
    return [json.loads(line) for line in (root / "events").read_text().splitlines()]


def assert_remote_stopped(root):
    stat = Path("/proc") / (root / "pid").read_text() / "stat"
    try:
        assert stat.read_text().split()[2] in {"Z", "X"}
    except (FileNotFoundError, ProcessLookupError):
        pass


@pytest.mark.asyncio
async def test_sandbox_worker_reuses_bridge_and_close_stops_remote_process(openshell):
    runtime, root = openshell
    try:
        assert await run(runtime) == "Verified."
        name = runtime.transport_status["sandbox_name"]
        assert len(name) <= 19
        assert runtime.transport_status["sandbox_active"]
        assert await run(runtime) == "Verified."
        assert runtime.last_run["worker_reused"]
        assert runtime.transport_status["sandbox_name"] == name
    finally:
        await runtime.close()
    commands = events(root)
    assert [args[args.index("sandbox") + 1] for args in commands] == ["create", "exec", "stop", "delete"]
    create, execute, stop, delete = commands
    assert "--no-auto-providers" in create and "--provider" not in create and "--upload" not in create
    assert create[create.index("--restart-policy") + 1] == "never"
    assert "--no-tty" in execute and "--no-login-shell" in execute
    assert "/usr/bin/env" in execute and "-i" in execute
    assert stop[-1] == delete[-1] == name
    assert_remote_stopped(root)
    assert runtime.transport_status == {"transport":"openshell", "sandbox_active":False,
                                         "sandbox_name":None, "sandbox_cleanup":"deleted"}
    await runtime.close()
    assert events(root) == commands  # Idempotent, with no unrelated sandbox operation.


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_interrupted_worker_is_stopped_without_replaying_model_or_tools(openshell, cancel):
    runtime, root = openshell
    worker = root / "worker.py"
    worker.write_text(worker.read_text().replace("for line in sys.stdin:", "time.sleep(60)\nfor line in sys.stdin:"))
    await runtime.start()
    if not cancel:
        runtime.config.agent_timeout_seconds = 0.2
    task = asyncio.create_task(run(runtime))
    try:
        if cancel:
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(AgentRuntimeError, match="timed out"):
                await task
        runtime.llm._create.assert_not_awaited()
        assert runtime.last_run["status"] == ("cancelled" if cancel else "timed_out")
        assert runtime.last_run["sandbox_cleanup"] == "deleted"
        assert not runtime.transport_status["sandbox_active"]
        assert_remote_stopped(root)
        assert len([item for item in events(root) if "create" in item]) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_unconfirmed_cleanup_blocks_new_sandboxes_and_exposes_receipt(openshell):
    runtime, root = openshell
    await runtime.start()
    (root / "fail-cleanup").touch()
    try:
        with pytest.raises(AgentRuntimeError, match="cleanup is pending"):
            await runtime.close()
        assert not runtime.worker_ready
        assert runtime.transport_status["sandbox_cleanup"] == "pending"
        name = runtime.transport_status["sandbox_name"]
        with pytest.raises(AgentRuntimeError, match="cleanup is pending"):
            await run(runtime)
        assert runtime.transport_status["sandbox_name"] == name
        assert len([item for item in events(root) if "create" in item]) == 1
        runtime.llm._create.assert_not_awaited()
    finally:
        (root / "fail-cleanup").unlink()
        await runtime.close()


@pytest.mark.asyncio
async def test_missing_cli_never_falls_back_to_local_hermes(openshell):
    runtime, root = openshell
    runtime.config.openshell_cli = str(root / "missing")
    with pytest.raises(AgentRuntimeError, match="CLI is missing"):
        await run(runtime)
    assert runtime._process is None and runtime._profile is None
    assert runtime.transport_status["sandbox_name"] is None
    runtime.llm._create.assert_not_awaited()


@pytest.mark.asyncio
async def test_broader_policy_is_rejected_before_sandbox_creation(openshell):
    runtime, root = openshell
    policy = root / "unsafe.yaml"
    policy.write_text('version: 1\nnetwork_policies: {internet: {}}\n')
    runtime.config.openshell_policy_path = str(policy)
    with pytest.raises(AgentRuntimeError, match="denied network"):
        await run(runtime)
    assert not (root / "events").exists()
    runtime.llm._create.assert_not_awaited()


def test_openshell_environment_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_HERMES_TRANSPORT", "openshell")
    monkeypatch.setenv("BLOB_OPENSHELL_GATEWAY", "blob-test")
    monkeypatch.setenv("BLOB_OPENSHELL_CLI", "/opt/openshell")
    config = BlobConfig.load(str(tmp_path / "missing.yaml"))
    assert config.hermes_transport == "openshell"
    assert config.openshell_gateway == "blob-test" and config.openshell_cli == "/opt/openshell"
