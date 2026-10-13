"""Passive runtime readiness and an offline test of the actual Hermes core."""

import argparse
import asyncio
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from blob.agents.hermes import HermesAgentWrapper, AgentRuntimeError
from blob.config import BlobConfig


async def doctor(config, *, probe=False):
    report = {"selected_runtime": config.agent_runtime, "model": config.model_name,
              "hermes_source": bool(config.hermes_source_path and
                                    (Path(config.hermes_source_path) / "run_agent.py").is_file()),
              "hermes_python": bool(config.hermes_python and Path(config.hermes_python).is_file()),
              "openshell_cli": shutil.which("openshell") is not None,
              "nemoclaw_cli": shutil.which("nemoclaw") is not None,
              "docker_socket": Path("/var/run/docker.sock").exists(),
              "sandbox_active": False}
    if probe:
        from openai.types.chat import ChatCompletion
        async def completion(**kwargs):
            return ChatCompletion.model_validate({"id": "blob-doctor", "object": "chat.completion",
                "created": 0, "model": "offline", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "Blob runtime ready."}, "finish_reason": "stop"}]})
        async def tool(name, args):
            raise AgentRuntimeError("Doctor must not execute tools.")
        async def event(kind, detail):
            pass
        runtime = HermesAgentWrapper(config, SimpleNamespace(_create=completion))
        try:
            reply = await runtime.run([{"role": "user", "content": "Say Blob runtime ready."}],
                "You are Blob. Reply briefly.", [], tool, event)
            report["hermes_probe"] = reply == "Blob runtime ready."
        except (AgentRuntimeError, OSError) as exc:
            report["hermes_probe"] = False
            report["error"] = str(exc)
        finally:
            await runtime.close()
        report["run"] = runtime.last_run
    return report


def main():
    parser = argparse.ArgumentParser(description="Inspect Blob's candidate agent runtime")
    parser.add_argument("command", choices=["doctor"])
    parser.add_argument("--probe", action="store_true", help="Run real Hermes with a synthetic local model reply; no cloud")
    args = parser.parse_args()
    report = asyncio.run(doctor(BlobConfig.load(), probe=args.probe))
    print(json.dumps(report, indent=2))
    if args.probe and not report.get("hermes_probe"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
