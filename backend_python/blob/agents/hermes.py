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

from blob.ai.context_budget import compact_browser_snapshots, prompt_size_bytes
from blob.ai.response_format import correction_messages, has_tool_protocol
from blob.privacy.controls import PrivacyBlocked

MAX_FRAME_BYTES = 1024 * 1024


class AgentRuntimeError(RuntimeError):
    pass


class HermesAgentWrapper:
    def __init__(self, config, llm, *, controls=None):
        self.config, self.llm, self.controls = config, llm, controls
        self.last_run = None
        self._lock = asyncio.Lock()
        self._process = None
        self._profile = None
        self._ready = False
        self._transport = None
        if getattr(config, "hermes_transport", "local") == "openshell":
            from blob.agents.openshell_transport import OpenShellWorkerTransport
            self._transport = OpenShellWorkerTransport(config)

    @property
    def worker_ready(self):
        return self._ready and self._process is not None and self._process.returncode is None

    @property
    def transport_status(self):
        return {"transport": "openshell" if self._transport else "local",
                "sandbox_active": bool(self._transport and self._transport.active and self.worker_ready),
                "sandbox_name": self._transport.name if self._transport else None,
                "sandbox_cleanup": self._transport.cleanup_status if self._transport else None}

    def command(self):
        source = Path(self.config.hermes_source_path).expanduser()
        python = Path(self.config.hermes_python or sys.executable).expanduser()
        if not self.config.hermes_source_path or not (source / "run_agent.py").is_file():
            raise AgentRuntimeError("Hermes is not configured. Run blob-agent doctor; see docs/agent_runtime.md.")
        if not python.is_file():
            raise AgentRuntimeError("The configured Hermes Python interpreter does not exist.")
        return [str(python), "-u", str(Path(__file__).with_name("hermes_worker.py")),
                "--source", str(source.resolve())]

    async def _send(self, frame):
        data = json.dumps(frame, ensure_ascii=False).encode() + b"\n"
        if len(data) > MAX_FRAME_BYTES:
            raise AgentRuntimeError("Hermes request exceeds the bridge size limit.")
        try:
            self._process.stdin.write(data)
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise AgentRuntimeError("Hermes worker stopped before answering. Run blob-agent doctor.") from exc

    async def _receive(self):
        try:
            line = await self._process.stdout.readline()
            frame = json.loads(line) if line else None
        except (ValueError, UnicodeError) as exc:
            raise AgentRuntimeError("Hermes returned an invalid bridge message.") from exc
        if not isinstance(frame, dict):
            raise AgentRuntimeError("Hermes worker stopped before answering. Run blob-agent doctor.")
        return frame

    async def _stop_worker(self):
        process, profile = self._process, self._profile
        self._process, self._profile, self._ready = None, None, False
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
        finally:
            try:
                if self._transport is not None:
                    # A remote worker can inherit the CLI's output pipe. On
                    # Python 3.12, wait() then waits for that pipe to close too;
                    # stop the remote sandbox before waiting for the CLI.
                    await self._transport.close()
            finally:
                try:
                    if process is not None:
                        try:
                            await asyncio.wait_for(process.wait(), timeout=3)
                        except asyncio.TimeoutError:
                            # A failed remote cleanup must retain its error and
                            # sandbox name, without leaving a pipe wait unbounded.
                            process._transport.close()
                finally:
                    if profile is not None:
                        profile.cleanup()

    async def _ensure_worker(self):
        if self.worker_ready:
            return
        await self._stop_worker()
        command = self.command() if self._transport is None else None
        if self._transport is None:
            self._profile = tempfile.TemporaryDirectory(prefix="blob-hermes-")
        env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
               if key in os.environ}
        env["PYTHONUNBUFFERED"] = "1"
        if self._profile is not None:
            env["BLOB_WORKER_PROFILE"] = self._profile.name
        try:
            self._process = await self._transport.launch() if self._transport else await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=env, cwd="/tmp",
                start_new_session=os.name == "posix", limit=MAX_FRAME_BYTES)
            # Preload the actual core without forwarding any conversation or credentials.
            await self._send({"type": "initialize", "model": self.config.model_name,
                              "max_iterations": self.config.agent_max_iterations})
            frame = await self._receive()
            if frame.get("type") != "ready":
                code = frame.get("code")
                detail = f" ({code})" if isinstance(code, str) and code.isidentifier() and len(code) <= 80 else ""
                raise AgentRuntimeError("Hermes could not initialize" + detail + ". Run blob-agent doctor.")
            self._ready = True
        except BaseException:
            await self._stop_worker()
            raise

    async def start(self):
        """Load Hermes ahead of terminal input; no cloud calls or user data."""
        async with self._lock:
            async with asyncio.timeout(self.config.agent_timeout_seconds):
                await self._ensure_worker()

    async def close(self):
        async with self._lock:
            await self._stop_worker()

    async def run(self, messages, system_prompt, tools, execute_tool, on_event):
        # One bridge conversation at a time, even outside the orchestrator lock.
        async with self._lock:
            return await self._run(messages, system_prompt, tools, execute_tool, on_event)

    async def _run(self, messages, system_prompt, tools, execute_tool, on_event):
        self.last_run = {"runtime": "hermes", "status": "starting", "model_calls": 0,
                         "tools": [], "duration_ms": 0, "worker_reused": self.worker_ready,
                         "startup_ms": 0, "model_duration_ms": 0, "tool_duration_ms": 0}
        self.last_run.update(self.transport_status)
        started = time.monotonic()
        try:
            if self.controls:
                self.controls.check(cloud=True)
            async with asyncio.timeout(self.config.agent_timeout_seconds):
                await self._ensure_worker()
                self.last_run["startup_ms"] = round((time.monotonic() - started) * 1000)
                await self._send({"messages": messages, "system_prompt": system_prompt,
                            "tools": tools, "model": self.config.model_name,
                            "max_iterations": self.config.agent_max_iterations})
                self.last_run["status"] = "running"
                names = {tool["name"] for tool in tools}
                while True:
                    frame = await self._receive()
                    if self.controls:
                        self.controls.check(cloud=True)
                    kind = frame.get("type")
                    if kind == "progress":
                        self.last_run["phase"] = str(frame.get("phase", ""))[:40]
                    elif kind == "model":
                        request = frame.get("request")
                        if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
                            raise AgentRuntimeError("Hermes returned an invalid model request.")
                        request["messages"] = compact_browser_snapshots(request["messages"])
                        if prompt_size_bytes(request["messages"]) > self.config.max_prompt_bytes:
                            raise AgentRuntimeError("Hermes reached Blob's context limit. Narrow the request.")
                        requested = request.get("tools", [])
                        if not isinstance(requested, list) or any(
                            tool.get("function", {}).get("name") not in names for tool in requested):
                            raise AgentRuntimeError("Hermes requested an unapproved tool schema.")
                        if self.last_run["model_calls"] >= self.config.agent_max_iterations:
                            raise AgentRuntimeError("Hermes reached the model-call budget. Check /agent before retrying completed actions.")
                        self.last_run["model_calls"] += 1
                        self.last_run.setdefault("first_model_ms", round((time.monotonic() - started) * 1000))
                        await on_event("model", {})
                        kwargs = {key: request[key] for key in
                                  ("messages", "tools", "tool_choice", "temperature", "max_tokens") if key in request}
                        kwargs.update(model=self.config.model_name, stream=False)
                        kwargs["max_tokens"] = min(int(kwargs.get("max_tokens") or 4096), 4096)
                        search_arguments = any(tool.get("function", {}).get("name") == "blob_web_search"
                                               for tool in requested)
                        try:
                            model_started = time.monotonic()
                            response = await self.llm._create(**kwargs)
                            if has_tool_protocol(response.choices[0].message.content, search_arguments=search_arguments):
                                if self.last_run["model_calls"] >= self.config.agent_max_iterations:
                                    raise AgentRuntimeError("The model returned malformed tool text; that completion was discarded.")
                                self.last_run["model_calls"] += 1
                                self.last_run["format_retries"] = self.last_run.get("format_retries", 0) + 1
                                kwargs["messages"] = correction_messages(kwargs["messages"])
                                if prompt_size_bytes(kwargs["messages"]) > self.config.max_prompt_bytes:
                                    raise AgentRuntimeError("The model returned malformed tool text; there is no room to repair it safely.")
                                response = await self.llm._create(**kwargs)
                                if has_tool_protocol(response.choices[0].message.content, search_arguments=search_arguments):
                                    raise AgentRuntimeError("The model returned malformed tool text again. Those generated actions were not executed.")
                        except (PrivacyBlocked, asyncio.CancelledError):
                            raise
                        except AgentRuntimeError:
                            raise
                        except Exception as exc:
                            raise AgentRuntimeError("The AI provider failed during the Hermes run. Check /agent for completed tools before retrying.") from exc
                        finally:
                            self.last_run["model_duration_ms"] += round((time.monotonic() - model_started) * 1000)
                        await self._send({"id": frame.get("id"), "result": response.model_dump(mode="json")})
                    elif kind == "tool":
                        name, args = frame.get("name"), frame.get("args")
                        if name not in names or not isinstance(args, dict):
                            raise AgentRuntimeError("Hermes requested a tool outside this turn's capabilities.")
                        await on_event("tool_start", {"name": name})
                        tool_started = time.monotonic()
                        try:
                            result = await execute_tool(name, args)
                        finally:
                            self.last_run["tool_duration_ms"] += round((time.monotonic() - tool_started) * 1000)
                        record = {"name": name, "success": result.success}
                        self.last_run["tools"].append(record)
                        await on_event("tool_complete", record)
                        await self._send({"id": frame.get("id"), "result": {"success": result.success, "output": result.output}})
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
                if self.last_run["status"] != "completed":
                    await self._stop_worker()
            finally:
                self.last_run["duration_ms"] = round((time.monotonic() - started) * 1000)
                self.last_run.update(self.transport_status)
