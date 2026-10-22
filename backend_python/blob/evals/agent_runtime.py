"""Compare complete synthetic conversations through both Blob runtimes.

--live sends only synthetic prompts and a generated red/blue image to Nebius.
The real Hermes core is used in both offline and live candidate runs. Camera
hardware is replaced with a deterministic local sensor; no personal frame is read.
"""

import argparse
import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

from openai.types.chat import ChatCompletion
from PIL import Image

from blob.ai.orchestrator import BlobOrchestrator
from blob.config import BlobConfig
from blob.evals.document_memory import OfflineEmbedding
from blob.evals.private_workflow import close_assistant
from blob.ipc.blob_service_pb2 import UserMessage
from blob.memory.vector_store import VectorStore
from blob.privacy.controls import PrivacyControls
from blob.skills.registry import SkillRegistry
from blob.skills.builtin.camera import CameraSkill
from blob.skills.builtin.reminder import ReminderSkill


async def discard(event):
    pass


def make_assistant(root, runtime, *, live):
    config = BlobConfig.load()
    config.agent_runtime = runtime
    config.hermes_source_path = config.hermes_source_path or str(Path(".runtime/hermes").resolve())
    config.hermes_python = config.hermes_python or str(Path(".runtime/hermes-venv/bin/python").absolute())
    config.memory_db_path, config.documents_dir_path = str(root / "memory"), str(root / "documents")
    config.skills_dir_path, config.reminders_db_path = str(root / "skills"), str(root / "reminders.sqlite3")
    # Same fast vision model for both runtimes; timeout recovery is checked separately.
    config.vision_model_name = "openbmb/MiniCPM-V-4_5"
    controls = PrivacyControls(root / "privacy.json")
    # This isolated evaluation explicitly opts in for its synthetic requests.
    controls.update(cloud_enabled=True)
    registry = SkillRegistry(root / "skills", controls=controls)
    registry.register(ReminderSkill(root / "reminders.sqlite3"))
    camera = SimpleNamespace(scan_calls=0, list_people=lambda: [])
    def scan():
        camera.scan_calls += 1
        return {"faces": 1, "full_bodies": 0, "recognized": [], "unknown_faces": 1}
    camera.scan = scan
    registry.register(CameraSkill(camera))
    blob = BlobOrchestrator(config, VectorStore(config.memory_db_path, embedding_function=OfflineEmbedding(),
        controls=controls), registry, SimpleNamespace(broadcast=discard), controls=controls)
    blob.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(
        is_capture_blocked=lambda: controls.paused,
        is_active=False, _broadcast_state=lambda *args: discard(None),
        monitor=SimpleNamespace(get_active_window=lambda: None)))
    blob._streaming_disabled = True
    if not live:
        async def generate(messages, system):
            return SimpleNamespace(content="Synthetic answer. <emote>IDLE</emote>")
        blob.llm.generate_from_messages = generate
        async def completion(**kwargs):
            return ChatCompletion.model_validate({"id":"offline","object":"chat.completion","created":0,
                "model":"offline","choices":[{"index":0,"message":{"role":"assistant",
                "content":"Synthetic answer. <emote>IDLE</emote>"},"finish_reason":"stop"}]})
        blob.llm._create = completion
    return blob, camera


async def evaluate(root, runtime, *, live):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    blob, camera = make_assistant(root, runtime, live=live)
    checks, calls = [], []
    create = blob.llm.client.chat.completions.create if live else blob.llm._create
    async def tracked(**kwargs):
        calls.append({"has_images": any(isinstance(item.get("content"), list) and
            any(part.get("type") == "image_url" for part in item["content"]) for item in kwargs["messages"])})
        return await create(**kwargs)
    if live:
        blob.llm.client.chat.completions.create = tracked
    else:
        blob.llm._create = tracked
    def check(name, passed, **details):
        checks.append({"name":name,"passed":bool(passed),**details})
        print(runtime + ": " + name + " " + ("PASS" if passed else "FAIL"), flush=True)
    async def send(text):
        started = time.monotonic()
        with redirect_stdout(StringIO()):
            answer = await blob.handle_user_message(UserMessage(text=text))
        return answer, round((time.monotonic()-started)*1000)
    try:
        path = root / "Synthetic photo with spaces.png"
        picture = Image.new("RGB", (160,80), "red")
        picture.paste("blue", (80,0,160,80))
        picture.save(path)
        before = len(calls)
        answer, ms = await send(str(path) + " Who is in this picture?")
        check("identity_question_stays_local", "can't establish who" in answer and len(calls)==before,
              latency_ms=ms)
        answer, ms = await send("Draft an email to professor@example.invalid requesting a one-day extension for a synthetic assignment.")
        check("draft_while_photo_selected", (not live or "extension" in answer.casefold()) and
              "couldn't" not in answer.casefold() and not any(call["has_images"] for call in calls[before:]),
              latency_ms=ms, answer=answer)
        if live:
            answer, ms = await send("Describe the colors in the selected picture.")
            check("photo_pixels_reach_vision", "red" in answer.casefold() and "blue" in answer.casefold()
                  and calls[-1]["has_images"], latency_ms=ms, answer=answer)
            answer, ms = await send("What about the right side?")
            check("photo_followup_retains_pixels", "blue" in answer.casefold() and calls[-1]["has_images"],
                  latency_ms=ms, answer=answer)
        before = len(calls)
        answer, ms = await send("Can you recognize me")
        check("camera_uses_local_sensor", camera.scan_calls==1 and "1 face" in answer and len(calls)==before,
              latency_ms=ms)
        await send("/privacy cloud off")
        before = len(calls)
        await send("Can you recognize me")
        answer, ms = await send("Draft another synthetic email.")
        check("cloud_off_blocks_model_but_preserves_camera", camera.scan_calls==2 and len(calls)==before
              and "Cloud assistance is off" in answer, latency_ms=ms)
        await send("/privacy cloud on")
        if live:
            blob.skill_registry.history.clear()
            actions = []
            reminder = blob.skill_registry.get_skill("reminder")
            execute_reminder = reminder.async_execute
            async def audited(args):
                result = await execute_reminder(args)
                if result.success:
                    actions.append(args.get("action", "set"))
                return result
            reminder.async_execute = audited
            answer, ms = await send("Remind me to review the synthetic runtime experiment in 60 minutes, then list reminders to verify it exists.")
            history = list(blob.skill_registry.history)
            pending = blob.skill_registry.get_skill("reminder").reminders
            check("reminder_created_once", len(pending)==1 and "synthetic" in pending[0]["message"].casefold(),
                  latency_ms=ms, answer=answer)
            check("multi_step_reminder_verification", actions.count("set")==1 and "list" in actions
                  and actions.index("set") < len(actions)-1 and actions[-1]=="list",
                  actions=actions, invocations=len(history))
            await close_assistant(blob)
            blob, camera = make_assistant(root, runtime, live=live)
            check("reminder_survives_backend_recreation", len(blob.skill_registry.get_skill("reminder").reminders)==1)
        await send("/privacy pause")
        before = len(calls)
        answer, ms = await send("Can you recognize me")
        check("privacy_pause_blocks_camera_and_model", "Privacy pause is active" in answer and len(calls)==before,
              latency_ms=ms)
        return {"runtime":runtime,"live":live,"passed":sum(c["passed"] for c in checks),
                "total":len(checks),"checks":checks}
    finally:
        await close_assistant(blob)


async def run(args):
    if args.live:
        config = BlobConfig.load()
        PrivacyControls(config.privacy_settings_path).check(cloud=True)
    reports = []
    for runtime in (["classic","hermes"] if args.runtime=="both" else [args.runtime]):
        print("Evaluating", runtime, flush=True)
        with tempfile.TemporaryDirectory(prefix="blob-runtime-eval-") as directory:
            report = await evaluate(Path(directory), runtime, live=args.live)
            reports.append(report)
            print(runtime + ": " + str(report["passed"]) + "/" + str(report["total"]), flush=True)
    output = {"scope":"synthetic conversation workflows; camera fixture; vision pipeline shared",
              "reports":reports}
    if args.output:
        Path(args.output).write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps(output,indent=2))
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime",choices=["classic","hermes","both"],default="both")
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))


if __name__=="__main__":
    main()
