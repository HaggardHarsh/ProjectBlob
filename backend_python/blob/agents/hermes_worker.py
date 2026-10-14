"""Warm stdio worker: loaded libraries, fresh agent and permissions per turn.

This module imports no Blob code, keeping upstream dependencies separate.
The parent performs every cloud request and tool operation.
"""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import gc
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
from types import SimpleNamespace


class DiscardOutput(io.TextIOBase):
    """Suppress upstream console output without filesystem access or buffering."""

    @property
    def encoding(self):
        return "utf-8"

    def write(self, text):
        return len(text)


def disable_relay_plugins():
    """Keep upstream plugin discovery outside Blob's mediated runtime.

    Hermes creates its Relay host lazily on the first conversation. Even an
    empty task profile can discover system plugins and initialize their native
    runtime. Use Hermes's own no-op host for every profile before preloading.
    The existing coordinator keeps its session hooks and points to this registry.
    """
    from agent import relay_runtime

    def host_for_profile(profile_key=None, *, create=True):
        return relay_runtime.NoopRelayRuntime(
            profile_key=profile_key or relay_runtime.current_profile_key(),
            reason="Blob owns inference, tool authorization and run receipts.")

    relay_runtime.HOST_REGISTRY.for_profile = host_for_profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    wire, incoming = sys.stdout, sys.stdin
    lock = threading.Lock()
    sequence = 0
    root = Path(os.environ["BLOB_WORKER_PROFILE"])
    profile = root / "task"

    def emit(frame):
        wire.write(json.dumps(frame, ensure_ascii=False) + "\n")
        wire.flush()

    def exchange(kind, **payload):
        nonlocal sequence
        with lock:
            sequence += 1
            emit({"type": kind, "id": sequence, **payload})
            response = json.loads(incoming.readline())
            if response.get("id") != sequence:
                raise RuntimeError("Invalid bridge response")
            return response["result"]

    def prepare_profile():
        profile.mkdir(mode=0o700)
        (profile / "config.yaml").write_text(
            "tools:\n  tool_search:\n    enabled: off\nagent:\n  environment_probe: false\n")
        os.chdir(profile)

    def clear_profile():
        os.chdir(root)
        shutil.rmtree(profile)

    try:
        initialize = json.loads(incoming.readline())
        if initialize.get("type") != "initialize":
            raise RuntimeError("Missing initialization frame")
        os.environ["HERMES_HOME"] = str(profile)
        os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
        sys.path.insert(0, str(Path(args.source).resolve()))
        prepare_profile()
        with DiscardOutput() as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            # Blob owns receipts. Do not retain upstream conversation logs in a
            # long-lived process or start its logging thread/file handlers.
            logging.disable(logging.CRITICAL)
            import hermes_logging
            hermes_logging.setup_logging = lambda **kwargs: profile / "logs"
            from run_agent import AIAgent
            from tools.registry import registry
            from openai.types.chat import ChatCompletion
            import toolsets

            disable_relay_plugins()

            def new_agent(model, max_iterations, tools):
                toolsets.TOOLSETS["blob"] = {"description": "Blob's per-turn capabilities",
                    "tools": [tool["name"] for tool in tools], "includes": []}
                agent = AIAgent(model=model, api_key="blob-bridge-no-provider-key",
                    base_url="http://127.0.0.1:1/v1", provider="custom", api_mode="chat_completions",
                    max_iterations=max_iterations, enabled_toolsets=["blob"], quiet_mode=True,
                    save_trajectories=False, skip_memory=True, skip_context_files=True,
                    load_soul_identity=False, skip_background_review=True)
                # Release the unused client's sockets before attaching Blob's bridge.
                agent.client.close()
                agent.client = None
                agent._skip_mcp_refresh = True
                agent.tools = [{"type": "function", "function": tool} for tool in tools]
                agent.valid_tool_names = {tool["name"] for tool in tools}
                return agent

            def attach_bridge(agent, completion):
                bridge = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),
                    api_key="blob-bridge-no-provider-key", base_url="http://127.0.0.1:1/v1",
                    close=lambda: None)
                agent.client = bridge
                agent._create_request_openai_client = lambda **kwargs: bridge
                agent._disable_streaming = True

            # Exercise lazy conversation imports with a local synthetic reply,
            # so the first real user message also benefits from preloading.
            warm_agent = new_agent(initialize["model"], 1, [])
            def warm_completion(**kwargs):
                return ChatCompletion.model_validate({"id": "preload", "object": "chat.completion",
                    "created": 0, "model": initialize["model"], "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Ready."}, "finish_reason": "stop"}]})
            attach_bridge(warm_agent, warm_completion)
            warm_agent.run_conversation("Initialize the local worker.",
                system_message="Reply briefly.", conversation_history=[])
            warm_agent.close()
            del warm_agent, warm_completion, initialize
            clear_profile()
            gc.collect()
            emit({"type": "ready"})

            def handle_turn(request):
                agent = None
                names = []
                prepare_profile()
                try:
                    for tool in request["tools"]:
                        name = tool["name"]
                        def handler(arguments, name=name, **kwargs):
                            return json.dumps(exchange("tool", name=name, args=arguments))
                        registry.register(name=name, toolset="blob", schema=tool,
                            handler=handler, check_fn=lambda: True)
                        names.append(name)
                    emit({"type": "progress", "phase": "initializing"})
                    agent = new_agent(request["model"], request["max_iterations"], request["tools"])

                    def completion(**kwargs):
                        kwargs["stream"] = False
                        return ChatCompletion.model_validate(exchange("model", request=kwargs))
                    attach_bridge(agent, completion)
                    emit({"type": "progress", "phase": "conversation"})
                    messages = request["messages"]
                    history = [item for item in messages[:-1] if item["role"] != "system"]
                    result = agent.run_conversation(messages[-1]["content"],
                        system_message=request["system_prompt"], conversation_history=history)
                    return {"type": "final", "answer": result.get("final_response", ""),
                            "completed": bool(result.get("completed", False))}
                finally:
                    if agent is not None:
                        agent.close()
                    for name in names:
                        registry.deregister(name)
                    toolsets.TOOLSETS["blob"]["tools"] = []
                    clear_profile()

            while line := incoming.readline():
                request = json.loads(line)
                result = handle_turn(request)
                # A final frame acknowledges cleanup, not just model completion.
                del request, line
                gc.collect()
                emit(result)
                del result
    except Exception as exc:
        emit({"type": "error", "code": type(exc).__name__})


if __name__ == "__main__":
    main()
