"""Exercise NVIDIA memory, a document study plan, and a persistent reminder.

Run with --live to use Nebius. All stores are temporary and all inputs synthetic.
The report contains synthetic answers and provider call metadata, never credentials.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace

from blob.ai.orchestrator import BlobOrchestrator
from blob.config import BlobConfig
from blob.evals.document_memory import OfflineEmbedding, make_pdf
from blob.ipc import blob_service_pb2 as pb
from blob.memory.vector_store import VectorStore
from blob.privacy.controls import PrivacyControls
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.registry import SkillRegistry

PREFERENCE = "I prefer study plans with exactly three short numbered steps."
PROJECT = "I am working on Project Orion."
BRIEF = "Project Orion study brief: HDL state machines and IoT sensors. Write one worked example and a short self-test."
PLAN_REQUEST = "Using my saved study preferences, make a study plan for this Project Orion brief."
REMINDER_REQUEST = "Remind me to review my Project Orion study plan in 15 seconds."


class Events:
    def __init__(self):
        self.notifications = []
        self.reminder = asyncio.Event()

    async def broadcast(self, event):
        if event.HasField("notification"):
            self.notifications.append(event.notification.text)
            if "REMINDER" in event.notification.text or "Overdue reminder" in event.notification.text:
                self.reminder.set()


def make_assistant(root, events, calls, *, live, model=None, memory_model=None):
    config = BlobConfig.load()
    config.memory_db_path = str(root / "memory")
    config.documents_dir_path = str(root / "documents")
    config.skills_dir_path = str(root / "skills")
    config.reminders_db_path = str(root / "reminders.sqlite3")
    config.privacy_settings_path = str(root / "private/privacy.json")
    config.vision_model_name = "off"  # This workflow exercises the PDF text layer.
    if model:
        config.model_name = model
    if memory_model:
        config.memory_model_name = memory_model
    if not live:
        config.nebius_api_key = "offline-evaluation"
    controls = PrivacyControls(config.privacy_settings_path)
    registry = SkillRegistry(config.skills_dir_path, controls=controls)
    reminder = ReminderSkill(config.reminders_db_path)
    reminder.set_dispatcher(events)
    registry.register(reminder)
    store = VectorStore(config.memory_db_path, embedding_function=OfflineEmbedding(), controls=controls)
    async def shield_state(active, reason):
        pass
    shield = SimpleNamespace(is_active=False, is_capture_blocked=lambda: controls.paused,
                             _broadcast_state=shield_state)
    blob = BlobOrchestrator(config, store, registry, events,
                            screen_sampler=SimpleNamespace(privacy_shield=shield), controls=controls)
    blob._streaming_disabled = True  # Collect complete response usage for the report.
    for role, engine in (("chat", blob.llm), ("memory", blob.semantic.llm)):
        original = engine._create
        async def record(_role=role, _engine=engine, _original=original, **kwargs):
            started = time.perf_counter()
            response = await _original(**kwargs)
            usage = getattr(response, "usage", None)
            calls.append({"role": _role, "model": _engine.model_name,
                          "served_model": getattr(response, "model", None),
                          "seconds": round(time.perf_counter() - started, 3),
                          "usage": usage.model_dump() if usage else None})
            return response
        engine._create = record
    if not live:
        async def reply(messages, system_prompt):
            text = messages[-1]["content"]
            if "Remind me" in text:
                return SimpleNamespace(content='```tool_call\n{"tool":"reminder","args":'
                    '{"action":"set","message":"review my Project Orion study plan","minutes":0.25}}\n```')
            if "Project Orion brief" in text:
                return SimpleNamespace(content="1. Review HDL state machines.\n2. Practice IoT sensors.\n"
                    "3. Write one worked example and a short self-test.\nSource: study_brief.pdf, page 1.")
            return SimpleNamespace(content="I'll remember your study preferences and project.")
        async def select(prompt, context, system_prompt):
            return SimpleNamespace(content="L1,M2")
        blob.llm.generate_from_messages = reply
        blob.semantic.llm.generate = select
    reminder.start()
    return blob


async def close_assistant(blob):
    runtime = getattr(blob, "agent_runtime", None)
    if runtime is not None:
        await runtime.close()
    await blob.skill_registry.close()
    engines = {id(engine): engine for engine in (blob.llm, blob.semantic.llm)}
    for engine in engines.values():
        await engine.client.close()


async def run_workflow(root, *, live=False, model=None, memory_model=None):
    root.mkdir(parents=True, exist_ok=True)
    events, calls, results = Events(), [], []
    blob = None

    def check(case, passed, **details):
        results.append({"case": case, "passed": bool(passed), **details})
        print(f"EVAL {case}: {'PASS' if passed else 'FAIL'}", flush=True)

    async def send(text, attachments=()):
        return await asyncio.wait_for(blob.handle_user_message(pb.UserMessage(
            text=text, attachments=attachments)), timeout=120)

    def open_assistant():
        return make_assistant(root, events, calls, live=live, model=model, memory_model=memory_model)

    try:
        blob = open_assistant()
        ack = await send(PREFERENCE + " " + PROJECT)
        consolidated = await asyncio.wait_for(blob.semantic.consolidate_once(), timeout=120)
        lasting, middle = blob.semantic.list_facts(), blob.semantic.list_middle()
        check("nvidia_classifies_grounded_long_and_middle_memories",
              consolidated > 0 and any(item["text"] == PREFERENCE for item in lasting)
              and any(item["text"] == PROJECT for item in middle)
              and all(item["metadata"].get("grounded") is True
                      and item["metadata"].get("consolidation_model") == blob.config.memory_model_name
                      for item in lasting + middle), acknowledgement=ack)
        check("nvidia_provider_call_completed", not live or any(
            call["role"] == "memory" and call["model"].lower().startswith("nvidia/") for call in calls))

        await close_assistant(blob)
        blob = open_assistant()
        check("grounded_memories_survive_store_reopen",
              any(item["text"] == PREFERENCE for item in blob.semantic.list_facts())
              and any(item["text"] == PROJECT for item in blob.semantic.list_middle()))

        path = root / "study_brief.pdf"
        make_pdf(path, [BRIEF])
        plan = await send(PLAN_REQUEST, [str(path)])
        steps = re.findall(r"(?m)^\s*\d+[.)]\s+", plan)
        lower = plan.casefold()
        personal_context = blob.semantic.document_context(PLAN_REQUEST)
        check("document_plan_uses_saved_preferences_and_source", len(steps) == 3
              and PREFERENCE in personal_context
              and "hdl" in lower and "iot" in lower and "study_brief.pdf" in lower,
              answer=plan, saved_user_context=personal_context)
        records = blob._result_library().records()
        saved = next((item for item in records if item["answer"] == plan), None)
        check("completed_plan_saved_locally", saved is not None)
        await send("/files forget all")
        path.unlink()
        await close_assistant(blob)
        blob = open_assistant()
        replay = await send("/results show " + saved["id"]) if saved else ""
        check("exact_plan_replay_after_source_deletion_and_reopen", replay == plan
              and not blob._document_library().records())

        started = time.time()
        confirmation = await send(REMINDER_REQUEST)
        reminder = blob.skill_registry.get_skill("reminder")
        pending = reminder.reminders
        invocation = list(blob.skill_registry.history)
        check("natural_language_request_executes_reminder_skill", len(pending) == 1
              and "orion" in pending[0]["message"].casefold()
              and 0 < pending[0]["due_at"] - time.time() <= 16
              and pending[0]["due_at"] >= started
              and any(item["name"] == "reminder" and item["success"]
                      and item["source"] == "model" for item in invocation), answer=confirmation)
        await close_assistant(blob)
        blob = open_assistant()
        check("reminder_survives_store_reopen", len(blob.skill_registry.get_skill("reminder").reminders) == 1)

        await send("/privacy cloud off")
        count = len(calls)
        blocked = await send("Can you explain my Project Orion study plan?")
        blocked_consolidation = await blob.semantic.consolidate_once()
        check("cloud_off_blocks_chat_and_nvidia_consolidation", len(calls) == count
              and "Cloud assistance is off" in blocked and blocked_consolidation == 0)
        await send("/privacy pause")
        episodes_before = blob.vector_store.episodic.count()
        blocked = await send("I prefer an entirely different study plan.")
        check("privacy_pause_blocks_new_chat_and_memory", "Privacy pause is active" in blocked
              and blob.vector_store.episodic.count() == episodes_before
              and not any("entirely different" in item["text"] for item in blob.semantic.list_facts()))
        try:
            await asyncio.wait_for(events.reminder.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
        check("local_reminder_delivers_while_paused_and_cloud_off", events.reminder.is_set()
              and any("orion" in note.casefold() and "REMINDER" in note for note in events.notifications)
              and not blob.skill_registry.get_skill("reminder").reminders and len(calls) == count,
              notifications=[note for note in events.notifications if "REMINDER" in note])
        memory_model_used = blob.config.memory_model_name
        chat_model_used = blob.config.model_name
    finally:
        if blob:
            await close_assistant(blob)
    return {"mode": "live" if live else "offline", "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_model": chat_model_used, "memory_model": memory_model_used, "vision": "off",
            "inputs": "Synthetic only; temporary isolated stores. Reopen checks reconstruct the assistant in this process.",
            "provider_calls": calls, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use Nebius with synthetic inputs and normal API billing")
    parser.add_argument("--model")
    parser.add_argument("--memory-model")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blob-private-workflow-") as directory:
        report = asyncio.run(run_workflow(Path(directory), live=args.live,
                                         model=args.model, memory_model=args.memory_model))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"mode": report["mode"], "passed": sum(item["passed"] for item in report["results"]),
                      "total": len(report["results"]), "provider_calls": len(report["provider_calls"])}))
    raise SystemExit(0 if all(item["passed"] for item in report["results"]) else 1)


if __name__ == "__main__":
    main()
