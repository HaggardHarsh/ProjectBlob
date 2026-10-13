"""Private stdio worker: Hermes chooses native calls; Blob executes them.

This module imports no Blob code, keeping upstream dependencies separate.
"""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    wire, incoming = sys.stdout, sys.stdin
    lock = threading.Lock()
    sequence = 0

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

    try:
        request = json.loads(incoming.readline())
        profile = os.environ["BLOB_WORKER_PROFILE"]
        with open(os.devnull, "w") as quiet:
            os.environ["HERMES_HOME"] = profile
            os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
            Path(profile, "config.yaml").write_text("tools:\n  tool_search:\n    enabled: off\n")
            os.chdir(profile)
            sys.path.insert(0, str(Path(args.source).resolve()))
            with redirect_stdout(quiet), redirect_stderr(quiet):
                from run_agent import AIAgent
                from tools.registry import registry
                from openai.types.chat import ChatCompletion
                import toolsets

                for tool in request["tools"]:
                    name = tool["name"]
                    def handler(arguments, name=name, **kwargs):
                        return json.dumps(exchange("tool", name=name, args=arguments))
                    registry.register(name=name, toolset="blob", schema={"name": name,
                        "description": tool["description"], "parameters": tool["parameters"]},
                        handler=handler, check_fn=lambda: True)
                toolsets.TOOLSETS["blob"] = {"description": "Blob's per-turn capabilities",
                    "tools": [tool["name"] for tool in request["tools"]], "includes": []}
                emit({"type": "progress", "phase": "initializing"})
                agent = AIAgent(model=request["model"], api_key="blob-bridge-no-provider-key",
                    base_url="http://127.0.0.1:1/v1", provider="custom", api_mode="chat_completions",
                    max_iterations=request["max_iterations"], enabled_toolsets=["blob"],
                    quiet_mode=True,
                    save_trajectories=False, skip_memory=True, skip_context_files=True,
                    load_soul_identity=False, skip_background_review=True)

                def completion(**kwargs):
                    kwargs["stream"] = False
                    return ChatCompletion.model_validate(exchange("model", request=kwargs))
                bridge = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)),
                    api_key="blob-bridge-no-provider-key", base_url="http://127.0.0.1:1/v1",
                    close=lambda: None)
                agent.client = bridge
                agent._create_request_openai_client = lambda **kwargs: bridge
                agent._disable_streaming = True
                # Hermes may append discovery helpers to a nonempty toolset.
                # This bridge exposes only the exact capabilities Blob supplied.
                agent.tools = [{"type": "function", "function": tool} for tool in request["tools"]]
                agent.valid_tool_names = {tool["name"] for tool in request["tools"]}
                emit({"type": "progress", "phase": "conversation"})
                messages = request["messages"]
                history = [item for item in messages[:-1] if item["role"] != "system"]
                result = agent.run_conversation(messages[-1]["content"],
                    system_message=request["system_prompt"], conversation_history=history)
                emit({"type": "final", "answer": result.get("final_response", ""),
                      "completed": bool(result.get("completed", False))})
                close = getattr(agent, "close", None)
                if close:
                    close()
    except Exception as exc:
        emit({"type": "error", "code": type(exc).__name__})


if __name__ == "__main__":
    main()
