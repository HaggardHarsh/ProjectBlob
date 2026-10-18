"""Check real daemon/overlay invitation delivery with synthetic data, no provider calls."""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from blob.evals.private_workflow import Events, make_assistant, close_assistant
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.server import start_grpc_server
from blob.privacy.window_monitor import WindowInfo
from blob.proactive import ProactiveConversation


async def validate(root, binary):
    os.environ.update(BLOB_IPC_ADDRESS="unix:" + str(root / "blob.sock"),
        BLOB_IPC_TOKEN_PATH=str(root / "private/ipc.token"), BLOB_AGENT_RUNTIME="classic")
    blob = make_assistant(root, Events(), [], live=False)
    blob.controls.update(proactive_enabled=True)
    blob.event_dispatcher = EventDispatcher()
    blob.llm._create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content="What's one small thing you enjoyed today?", tool_calls=None))]))
    blob.llm._chat_kwargs = lambda: {}
    now = datetime.now().replace(hour=13, minute=0, second=0, microsecond=0).timestamp()
    mono = 10000.0
    window = WindowInfo("Synthetic document", "gedit", 1, (0, 0, 700, 500), "synthetic-window", "gnome")
    shield = SimpleNamespace(is_active=False, blacklist=SimpleNamespace(is_blacklisted=lambda window: False))
    probe = SimpleNamespace(shield=shield, sample=lambda: (window, 30))
    feature = ProactiveConversation(blob, clock=lambda: now, monotonic=lambda: mono, probe=probe)
    blob.proactive = feature
    feature.started = feature.last_user = mono - 4000
    feature.state["next_at"] = now - 1
    feature._focus, feature._focus_since = window.identity, mono - 200
    server, servicer = await start_grpc_server(blob.config, blob, blob.event_dispatcher)
    process = None
    checks = []
    try:
        process = await asyncio.create_subprocess_exec(str(binary), "--frames", "900", "--settings", str(root / "desktop.json"),
            env={**os.environ, "SDL_VIDEODRIVER": "dummy"}, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        async def wait_for(condition, seconds=10):
            deadline = time.monotonic() + seconds
            while not condition():
                if time.monotonic() >= deadline or process.returncode is not None:
                    raise RuntimeError("Synthetic overlay validation timed out")
                await asyncio.sleep(0.05)
        await wait_for(lambda: bool(feature.clients))
        checks.append({"case": "real_overlay_reports_compatible_presence", "passed": True})
        before = blob.vector_store.episodic.count()
        offered = await feature.tick()
        checks.append({"case": "backend_sends_bounded_bubble", "passed": offered})
        await wait_for(lambda: feature.pending and feature.pending["shown"])
        checks.append({"case": "compiled_overlay_decodes_renders_and_acknowledges", "passed": True})
        checks.append({"case": "invitation_does_not_create_user_memory", "passed": blob.vector_store.episodic.count() == before})
        checks.append({"case": "same_session_cannot_offer_again", "passed": not await feature.tick()})
        control = await asyncio.create_subprocess_exec(str(binary.parent / "blob_ipc_smoke"),
            blob.config.ipc_address, "--mute", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(control.communicate(), 10)
        checks.append({"case": "mute_persists_and_prevents_further_inference", "passed": not await feature.tick() and
            blob.llm._create.await_count == 1 and not feature.enabled and control.returncode == 0})
        return {"mode": "synthetic-real-cpp-overlay", "real_provider_calls": 0, "checks": checks,
                "passed": all(check["passed"] for check in checks)}
    finally:
        if process and process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.communicate(), 5)
        await servicer.close_streams()
        await server.stop(grace=1)
        await close_assistant(blob)
        blob.vector_store.client._system.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blob-proactive-desktop-") as temporary:
        report = asyncio.run(validate(Path(temporary), args.binary.resolve()))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
