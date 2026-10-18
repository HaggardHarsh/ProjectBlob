"""Bounded real-model invitation audit with synthetic context and temporary stores."""

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from blob.evals.private_workflow import Events, make_assistant, close_assistant
from blob.ipc import blob_service_pb2 as pb
from blob.ipc.event_dispatcher import EventDispatcher
from blob.privacy.window_monitor import WindowInfo
from blob.proactive import DAY, ProactiveConversation


async def evaluate(root):
    calls, inputs, completions, checks = [], [], [], []
    blob = make_assistant(root, Events(), calls, live=True)
    blob.controls.update(proactive_enabled=True)
    original = blob.llm._create
    async def capture(**kwargs):
        inputs.append(kwargs["messages"])
        if "tools" in kwargs or len(inputs) > 6:
            raise RuntimeError("Invitation audit attempted tools or exceeded its call budget")
        response = await original(**kwargs)
        completions.append(response.choices[0].message.content)
        return response
    blob.llm._create = capture
    now = [datetime.now().replace(hour=13, minute=0, second=0, microsecond=0).timestamp(), 10000.0]
    window = WindowInfo("Synthetic editor", "gedit", 1, (0, 0, 800, 600), "synthetic-window", "gnome")
    shield = SimpleNamespace(is_active=False, blacklist=SimpleNamespace(is_blacklisted=lambda window: False))
    probe = SimpleNamespace(shield=shield, sample=lambda: (window, 30))
    target = ["social:day"]
    rng = SimpleNamespace(choice=lambda rows: next(row for row in rows if row[0] == target[0]), uniform=lambda a, b: 60)
    feature = ProactiveConversation(blob, clock=lambda: now[0], monotonic=lambda: now[1], rng=rng, probe=probe)
    blob.proactive = feature
    blob.event_dispatcher = EventDispatcher()
    queue = asyncio.Queue(maxsize=10)
    blob.event_dispatcher.register_client(1, queue)
    episode = blob.episodic.add_episode("I enjoy photography.", "Okay.")
    blob.vector_store.store("I enjoy photography.", {"grounded": True, "source_episode_id": episode,
        "timestamp": now[0], "tier": "long"}, collection="semantic")
    blob.vector_store.store("Synthetic private bank code: DO-NOT-SHARE-891", {"grounded": True,
        "source_episode_id": episode, "timestamp": now[0], "tier": "long"}, collection="semantic")
    blob.awareness = SimpleNamespace(context=lambda: "Working with code in an editor. Detected topics: Python.")
    try:
        for topic in ("social:day", "social:small_win", "interest:photography", "screen:Python", "social:unwind"):
            target[0] = topic
            now[0] += 3 * DAY
            now[1] += 3 * DAY
            feature._focus, feature._focus_since = window.identity, now[1] - 180
            feature.presence(1, pb.HeartbeatPing(client_kind=pb.HeartbeatPing.OVERLAY, proactive_bubbles=True,
                overlay_visible=True, desktop_width=1920, desktop_height=1080))
            before = blob.vector_store.episodic.count()
            passed = await feature.tick()
            event = queue.get_nowait() if not queue.empty() else None
            check = {"case": topic, "passed": bool(passed and event and event.notification.image_bmp and
                before == blob.vector_store.episodic.count()), "opening": event.notification.text if event else None}
            checks.append(check)
            print(topic + ": " + ("PASS" if check["passed"] else "FAIL"), flush=True)
            if event:
                await feature.feedback(1, pb.ProactiveFeedback(approach_id=event.notification.approach_id,
                    action=pb.ProactiveFeedback.SHOWN))
                feature.take_reply()
        checks.append({"case": "private_memory_never_sent", "passed": "DO-NOT-SHARE-891" not in json.dumps(inputs)})
        before = len(calls)
        await feature.command("/proactive off")
        checks.append({"case": "mute_makes_no_provider_call", "passed": not await feature.tick() and len(calls) == before})
        return {"mode": "real-model-synthetic-invitations", "checks": checks, "provider_calls": calls,
                "synthetic_completions": completions,
                "passed": all(check["passed"] for check in checks)}
    finally:
        await close_assistant(blob)
        blob.vector_store.client._system.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blob-proactive-audit-") as temporary:
        report = asyncio.run(evaluate(Path(temporary)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "provider_calls": len(report["provider_calls"])}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
