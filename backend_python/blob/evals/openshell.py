"""Real OpenShell integration checks with synthetic inference and no cloud calls."""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from openai.types.chat import ChatCompletion

from blob.agents.hermes import HermesAgentWrapper
from blob.config import BlobConfig
from blob.skills.base import SkillResult


def completion(text="Verified.", *, tool=False):
    message = {"role": "assistant", "content": text}
    if tool:
        message.update(content=None, tool_calls=[{"id":"synthetic-call", "type":"function",
            "function":{"name":"blob_check", "arguments":'{"value":"synthetic"}'}}])
    return ChatCompletion.model_validate({"id":"synthetic", "object":"chat.completion",
        "created":0, "model":"offline", "choices":[{"index":0, "message":message,
        "finish_reason":"tool_calls" if tool else "stop"}]})


async def evaluate(config):
    config = config.model_copy(update={"hermes_transport":"openshell"})
    runtime = None
    task = None
    calls, tools = [], []
    answers = iter([completion(tool=True), completion(), completion()])
    async def model(**kwargs):
        calls.append(kwargs)
        return next(answers)
    async def execute(name, args):
        tools.append((name, args))
        return SkillResult("Synthetic tool completed on the host.", True, "SUCCESS")
    async def event(*args):
        pass
    runtime = HermesAgentWrapper(config, SimpleNamespace(_create=model))
    report = {"scope":"real OpenShell/Hermes; synthetic local inference; no cloud or personal data",
              "checks":{}, "runs":[]}
    try:
        await runtime.start()
        report["checks"]["preload_without_inference"] = not calls
        name = runtime.transport_status["sandbox_name"]
        transport = runtime._transport
        script = '''import errno,os,json,socket
from pathlib import Path
checks={'non_root':os.getuid()==1000,'no_provider_keys':all(k not in os.environ for k in ('NEBIUS_API_KEY','OPENAI_API_KEY'))}
try:
 Path('/opt/blob/forbidden-write').write_text('synthetic')
 checks['readonly_code']=False
except PermissionError:
 checks['readonly_code']=True
try:
 socket.create_connection(('1.1.1.1',443),timeout=2).close()
 checks['network_blocked']=False
except OSError as error:
 checks['network_blocked']=error.errno in (errno.EPERM,errno.EACCES,errno.ENETUNREACH)
status=Path('/proc/self/status').read_text()
checks['no_new_privileges']='NoNewPrivs:\\t1' in status
checks['seccomp']='Seccomp:\\t2' in status
print(json.dumps(checks))
'''
        # The probe runs under the same identity and policy as the worker.
        result = await transport._control("sandbox", "exec", "--name", name,
            "--no-tty", "--no-login-shell", "--", "/usr/bin/env", "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin", "/usr/local/bin/python", "-c", script)
        report["checks"].update(json.loads(result))
        capability = {"name":"blob_check", "description":"Synthetic local check.", "parameters":{
            "type":"object", "properties":{"value":{"type":"string"}}, "required":["value"]}}
        first = await runtime.run([{"role":"user", "content":"First synthetic turn."}],
            "Reply briefly.", [capability], execute, event)
        report["runs"].append(dict(runtime.last_run))
        second = await runtime.run([{"role":"user", "content":"Second synthetic turn."}],
            "Reply briefly.", [], execute, event)
        report["runs"].append(dict(runtime.last_run))
        report["checks"].update(
            native_host_tool=tools == [("blob_check", {"value":"synthetic"})],
            replies=first == second == "Verified.",
            warm_worker=runtime.last_run["worker_reused"] and runtime.transport_status["sandbox_name"] == name,
            fresh_history="First synthetic turn." not in json.dumps(calls[-1]["messages"]),
            fresh_permissions=not calls[-1].get("tools"))
        entered = asyncio.Event()
        async def wait_for_cancel(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        runtime.llm._create = wait_for_cancel
        task = asyncio.create_task(runtime.run([{"role":"user", "content":"Synthetic cancellation."}],
            "Reply briefly.", [], execute, event))
        await asyncio.wait_for(entered.wait(), timeout=config.agent_timeout_seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        report["runs"].append(dict(runtime.last_run))
        report["checks"]["cancel_stops_sandbox"] = (
            runtime.last_run["status"] == "cancelled" and not runtime.worker_ready and
            runtime.transport_status["sandbox_name"] is None and
            runtime.transport_status["sandbox_cleanup"] in {"deleted", "stopped; deletion pending"})
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await runtime.close()
    report["passed"] = all(report["checks"].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--local-gateway", action="store_true", help="Use tools/openshell_gateway.py's project-local registration")
    parser.add_argument("--startup-timeout", type=int, default=120, help="Allow initial runtime image pulls (maximum 600 seconds)")
    args = parser.parse_args()
    config = BlobConfig.load()
    config = config.model_copy(update={"agent_timeout_seconds":max(5, min(600, args.startup_timeout))})
    if args.local_gateway:
        root = Path(__file__).resolve().parents[3] / ".runtime/openshell"
        config = config.model_copy(update={"openshell_cli":str(root / "bin/openshell"),
            "openshell_config_dir":str(root / "config"), "openshell_gateway":"blob"})
    report = asyncio.run(evaluate(config))
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output, end="")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
