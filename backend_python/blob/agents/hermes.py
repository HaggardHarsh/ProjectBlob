"""Hermes loop with all inference and tools mediated by Blob.

Workers receive no provider credentials or default Hermes tools. Blob owns
deadlines, authorization, cloud calls, memory and cancellation. A failed run
never silently falls back to the classic loop.
"""

import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

from blob.ai.context_budget import prompt_size_bytes
from blob.privacy.controls import PrivacyBlocked

MAX_FRAME_BYTES = 1024 * 1024


class AgentRuntimeError(RuntimeError):
    pass


class HermesAgentWrapper:
    def __init__(self, config, llm, *, controls=None):
        self.config, self.llm, self.controls = config, llm, controls
        self.last_run = None

    def command(self):
        source = Path(self.config.hermes_source_path).expanduser()
        python = Path(self.config.hermes_python or sys.executable).expanduser()
        if not self.config.hermes_source_path or not (source / "run_agent.py").is_file():
            raise AgentRuntimeError("Hermes is not configured. Run blob-agent doctor; see docs/agent_runtime.md.")
        if not python.is_file():
            raise AgentRuntimeError("The configured Hermes Python interpreter does not exist.")
        return [str(python), "-u", str(Path(__file__).with_name("hermes_worker.py")),
                "--source", str(source.resolve())]

    async def run(self, messages, system_prompt, tools, execute_tool, on_event):
        self.last_run = {"runtime": "hermes", "status": "starting", "model_calls": 0,
                         "tools": [], "duration_ms": 0}
        started = time.monotonic()
        process = None
        profile = tempfile.TemporaryDirectory(prefix="blob-hermes-")
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
               if key in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        env["BLOB_WORKER_PROFILE"] = profile.name
        try:
            if self.controls:
                self.controls.check(cloud=True)
            command = self.command()
            async with asyncio.timeout(self.config.agent_timeout_seconds):
                process = await asyncio.create_subprocess_exec(
                    *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=env, cwd="/tmp",
                    start_new_session=os.name == "posix", limit=MAX_FRAME_BYTES)
                async def send(frame):
                    data = json.dumps(frame, ensure_ascii=False).encode() + b"\n"
                    if len(data) > MAX_FRAME_BYTES:
                        raise AgentRuntimeError("Hermes request exceeds the bridge size limit.")
                    process.stdin.write(data)
                    await process.stdin.drain()
                await send({"messages": messages, "system_prompt": system_prompt,
                            "tools": tools, "model": self.config.model_name,
                            "max_iterations": self.config.agent_max_iterations})
                self.last_run["status"] = "running"
                names = {tool["name"] for tool in tools}
                while True:
                    try:
                        line = await process.stdout.readline()
                        frame = json.loads(line) if line else None
                    except (ValueError, UnicodeError) as exc:
                        raise AgentRuntimeError("Hermes returned an invalid bridge message.") from exc
                    if not isinstance(frame, dict):
                        raise AgentRuntimeError("Hermes worker stopped before answering. Run blob-agent doctor.")
                    if self.controls:
                        self.controls.check(cloud=True)
                    kind = frame.get("type")
                    if kind == "progress":
                        self.last_run["phase"] = str(frame.get("phase", ""))[:40]
                    elif kind == "model":
                        request = frame.get("request")
                        if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
                            raise AgentRuntimeError("Hermes returned an invalid model request.")
                        if prompt_size_bytes(request["messages"]) > self.config.max_prompt_bytes:
                            raise AgentRuntimeError("Hermes reached Blob's context limit. Narrow the request.")
                        requested = request.get("tools", [])
                        if not isinstance(requested, list) or any(
                            tool.get("function", {}).get("name") not in names for tool in requested):
                            raise AgentRuntimeError("Hermes requested an unapproved tool schema.")
                        if self.last_run["model_calls"] >= self.config.agent_max_iterations:
                            raise AgentRuntimeError("Hermes reached the model-call budget. Check /agent before retrying completed actions.")
                        self.last_run["model_calls"] += 1
                        await on_event("model", {})
                        kwargs = {key: request[key] for key in
                                  ("messages", "tools", "tool_choice", "temperature", "max_tokens") if key in request}
                        kwargs.update(model=self.config.model_name, stream=False)
                        kwargs["max_tokens"] = min(int(kwargs.get("max_tokens") or 4096), 4096)
                        try:
                            response = await self.llm._create(**kwargs)
                        except (PrivacyBlocked, asyncio.CancelledError):
                            raise
                        except Exception as exc:
                            raise AgentRuntimeError("The AI provider failed during the Hermes run. Check /agent for completed tools before retrying.") from exc
                        await send({"id": frame.get("id"), "result": response.model_dump(mode="json")})
                    elif kind == "tool":
                        name, args = frame.get("name"), frame.get("args")
                        if name not in names or not isinstance(args, dict):
                            raise AgentRuntimeError("Hermes requested a tool outside this turn's capabilities.")
                        await on_event("tool_start", {"name": name})
                        result = await execute_tool(name, args)
                        record = {"name": name, "success": result.success}
                        self.last_run["tools"].append(record)
                        await on_event("tool_complete", record)
                        await send({"id": frame.get("id"), "result": {"success": result.success, "output": result.output}})
                    elif kind == "final":
                        answer = frame.get("answer")
                        if not isinstance(answer, str) or not answer.strip() or frame.get("completed") is not True:
                            raise AgentRuntimeError("Hermes did not complete the request within its task budget.")
                        self.last_run["status"] = "completed"
                        return answer
                    elif kind == "error":
                        raise AgentRuntimeError("Hermes could not finish (" +
                                                str(frame.get("code", "runtime_error"))[:80] + "). Run blob-agent doctor.")
                    else:
                        raise AgentRuntimeError("Hermes returned an unknown bridge message.")
        except asyncio.CancelledError:
            self.last_run["status"] = "cancelled"
            raise
        except PrivacyBlocked:
            self.last_run["status"] = "blocked"
            raise
        except TimeoutError as exc:
            self.last_run["status"] = "timed_out"
            raise AgentRuntimeError("Hermes timed out. Its worker was stopped; check /reminders before retrying a reminder.") from exc
        except Exception:
            self.last_run["status"] = "failed"
            raise
        finally:
            try:
                if process is not None:
                    try:
                        if process.returncode is None:
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            finally:
                profile.cleanup()
                self.last_run["duration_ms"] = round((time.monotonic() - started) * 1000)
