"""Multi-turn conversation regression catalog with isolated stores and fake sensors.

Offline mode verifies routing, prompt evidence, persistence and tool receipts.
--live additionally checks real model answers; only synthetic text reaches the API.
"""

import argparse
import asyncio
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from io import StringIO
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace

from openai.types.chat import ChatCompletion
from PIL import Image

from blob.ai.response_format import has_tool_protocol
from blob.evals.conversation_audit import FixtureWeb, make_assistant
from blob.evals.document_memory import make_pdf
from blob.evals.private_workflow import close_assistant
from blob.ipc import blob_service_pb2 as pb
from blob.privacy.blacklist import BlacklistManager
from blob.privacy.shield import PrivacyShield
from blob.privacy.window_monitor import WindowInfo
from blob.skills.builtin.camera import CameraSkill
from blob.skills.builtin.screen_capture import ScreenCaptureSkill
from blob.vision.camera import CameraVision


@dataclass(frozen=True)
class Turn:
    request: str
    tools: tuple[str, ...] = ()
    provider: str = "allowed"
    expect: tuple[str, ...] = ()
    model_expect: tuple[str, ...] = ()
    model_avoid: tuple[str, ...] = ()
    model_pattern: str = ""
    system_quote: str = ""
    restart: bool = False
    window: str = ""
    attach: bool = False


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: tuple[Turn, ...]
    enrolled: bool = False


def catalog():
    cases = []
    for number, question in enumerate((
        "Hi do you remember my face", "Do you still remember my face?",
        "Have you saved my face?", "Do you have my face stored yet?",
        "Is my face still saved?", "Hey, have you still got my face saved?",
        "Do you remember my face from last time?", "Do you remember what I look like?",
    ), 1):
        cases.append(Scenario(f"face_memory_wording_{number}", (
            Turn(question, tools=("camera",), provider="forbidden", expect=("Luma",)),
            Turn("do ti", provider="forbidden", expect=("mention 'camera'", "/camera scan")),
            Turn("did you?", provider="forbidden", expect=("mention 'camera'",)),
            Turn("yes please", provider="forbidden", expect=("mention 'camera'",)),
        ), enrolled=True))
    cases.extend((
        Scenario("no_face_enrollment", (
            Turn("Do you remember my face?", tools=("camera",), provider="forbidden", expect=("No face profiles",)),
            Turn("go for it", provider="forbidden", expect=("mention 'camera'",)),
            Turn("scan my camera", tools=("camera",), provider="forbidden", expect=("No face profiles",)),
        )),
        Scenario("saved_profile_unmatched_and_restarted", (
            Turn("scan my camera", tools=("camera",), provider="forbidden", expect=("Saved face profiles are still present",)),
            Turn("Do you remember my face?", tools=("camera",), provider="forbidden", expect=("Luma",), restart=True),
            Turn("/camera forget Luma", tools=("camera",), provider="forbidden", expect=("Forgot Luma",)),
            Turn("Do you remember my face?", tools=("camera",), provider="forbidden", expect=("No face profiles",), restart=True),
        ), enrolled=True),
        Scenario("camera_guidance_after_topic_change", (
            Turn("Do you remember my face?", tools=("camera",), provider="forbidden"),
            Turn("Tell me one fact about octopuses.", provider="required", model_expect=("octopus",)),
            Turn("thanks", provider="forbidden", expect=("welcome",)),
            Turn("yes", provider="forbidden", expect=("Okay",)),
        ), enrolled=True),
        Scenario("name_reason_and_correction", (
            Turn("Call me Luma.", provider="required"),
            Turn("What do you call me?", provider="required", system_quote="Call me Luma.", model_expect=("Luma",)),
            Turn("Why that so", provider="required", system_quote="Call me Luma.",
                 model_pattern=r"(?:you (?:asked|told|requested|wanted)|your (?:request|preference))", model_avoid=("misspoke", "misspoken")),
            Turn("Actually, call me Moss.", provider="required"),
            Turn("What do you call me?", provider="required", restart=True,
                 system_quote="Actually, call me Moss.", model_expect=("Moss",), model_avoid=("Luma",)),
            Turn("Why?", provider="required", system_quote="Actually, call me Moss.",
                 model_expect=("Moss",), model_pattern=r"(?:you (?:asked|told|requested|wanted|said|chose)|your (?:request|preference))"),
        )),
        Scenario("name_after_long_topic_change", (
            Turn("Call me Luma.", provider="required"),
            *(Turn(f"What is {number} plus {number}? Just the answer.", provider="required",
                   model_expect=(str(number * 2),)) for number in range(11, 18)),
            Turn("What do you call me?", provider="required", system_quote="Call me Luma.", model_expect=("Luma",)),
        )),
        Scenario("declined_draft_stays_closed", (
            Turn("Draft one sentence to alex@example.invalid saying Project Cobalt is finished.",
                 provider="required", model_expect=("Cobalt",)),
            Turn("Nah not really. We are done with that", provider="forbidden", expect=("leave that",)),
            Turn("sure", provider="forbidden", expect=("Okay",)),
            Turn("thanks", provider="forbidden", expect=("welcome",)),
            Turn("What is 17 times 6? Just the answer.", provider="required", model_expect=("102",), model_avoid=("Cobalt", "email")),
        )),
        Scenario("camera_denial_and_topic_switch", (
            Turn("Don't open my camera. Tell me what a prime number is.", provider="required", model_expect=("prime",)),
            Turn("sure", provider="allowed"),
            Turn("/camera scan", tools=("camera",), provider="forbidden", expect=("Camera opened successfully",)),
        )),
        Scenario("screen_request_overrides_old_pdf", (
            Turn("Summarize the attached study brief.", provider="required", attach=True, model_expect=("HDL",)),
            Turn("What is happening on my screen rn?", tools=("screen_capture",), provider="required",
                 model_expect=("voltage",), model_avoid=("HDL", "IoT")),
        )),
        Scenario("unknown_window_explains_missing_bridge", (
            Turn("Can you see my screen?", tools=("screen_capture",), provider="forbidden", window="unknown",
                 expect=("active window", "bridge")),
            Turn("/privacy resume", provider="forbidden", expect=("resumed",)),
            Turn("What is on my screen?", tools=("screen_capture",), provider="forbidden", expect=("active window",)),
        )),
        Scenario("sensitive_window_recovers", (
            Turn("What is on my screen?", tools=("screen_capture",), provider="forbidden", window="sensitive", expect=("privacy shield",)),
            Turn("What is on my screen?", tools=("screen_capture",), provider="required", window="safe", model_expect=("voltage",)),
        )),
        Scenario("cloud_off_and_privacy_pause", (
            Turn("/privacy cloud off", provider="forbidden", expect=("off",)),
            Turn("What is 17 times 6?", provider="forbidden", expect=("Cloud assistance is off",)),
            Turn("Do you remember my face?", tools=("camera",), provider="forbidden", expect=("Luma",)),
            Turn("scan my camera", tools=("camera",), provider="forbidden", expect=("Camera opened successfully",)),
            Turn("/privacy pause", provider="forbidden", expect=("paused",)),
            Turn("scan my camera", provider="forbidden", expect=("Privacy pause is active",)),
            Turn("/camera list", tools=("camera",), provider="forbidden", expect=("Luma",)),
            Turn("/privacy resume", provider="forbidden", expect=("resumed",)),
            Turn("scan my camera", tools=("camera",), provider="forbidden", expect=("Camera opened successfully",)),
        ), enrolled=True),
        Scenario("no_questions_and_topic_change", (
            Turn("I miss home tonight. No advice or questions, please.", provider="required", model_avoid=("?",)),
            Turn("Distract me with one silly sentence. No questions.", provider="required", model_avoid=("?",)),
            Turn("What is 9 times 8? Just the answer.", provider="required", model_expect=("72",)),
        )),
    ))
    return cases


class FixtureCamera(CameraVision):
    """Keep real enrollment storage and skill routing; replace all camera access."""
    def _open(self, cv2):
        raise AssertionError("Conversation sweeps must never open a camera")

    def scan(self):
        return {"faces": 1, "full_bodies": 0, "recognized": [], "unknown_faces": 1}

    def status(self):
        return "Synthetic camera opened and returned a frame."

    def enroll(self, name):
        raise AssertionError("This catalog does not authorize enrollment")


async def offline_completion(**kwargs):
    return ChatCompletion.model_validate({"id": "conversation-sweep", "object": "chat.completion", "created": 0,
        "model": "offline-host-check", "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "Synthetic offline model response."}, "finish_reason": "stop"}]})


def response_checks(turn, answer, receipts, calls, prompts, *, live):
    checks = {"nonempty": bool(answer.strip()), "no_protocol_leak": not has_tool_protocol(answer),
              "expected_tools": tuple(item["name"] for item in receipts) == turn.tools,
              "local_response": all(text.casefold() in answer.casefold() for text in turn.expect)}
    if turn.provider != "allowed":
        checks["provider_boundary"] = bool(calls) == (turn.provider == "required")
    if turn.system_quote:
        checks["original_user_evidence_in_prompt"] = any(turn.system_quote in prompt for prompt in prompts)
    semantic = bool(turn.model_expect or turn.model_avoid or turn.model_pattern)
    if live and semantic:
        checks["model_answer"] = (all(text.casefold() in answer.casefold() for text in turn.model_expect)
            and not any(text.casefold() in answer.casefold() for text in turn.model_avoid)
            and (not turn.model_pattern or bool(re.search(turn.model_pattern, answer, re.I))))
    return checks, semantic and not live


async def evaluate(root, scenario, runtime, *, live, budget):
    calls, prompts, turns, web = [], [], [], FixtureWeb()
    window = ["safe"]
    blob = None
    systems = []
    initialized = False

    def open_assistant():
        nonlocal initialized
        assistant, _ = make_assistant(root, runtime, web, calls, budget,
            completion=None if live else offline_completion)
        systems.append(assistant.vector_store.client._system)
        vision = FixtureCamera(assistant.config)
        if scenario.enrolled and not initialized:
            person = "a" * 32
            (vision.face_db_path / person).mkdir(parents=True)
            Image.new("L", (100, 100), 120).save(vision.face_db_path / person / "00.png")
            vision._save_index({person: "Luma"})
        initialized = True
        assistant.skill_registry.register(CameraSkill(vision))
        shield = PrivacyShield.__new__(PrivacyShield)
        shield.controls, shield.is_active = assistant.controls, False
        shield.awareness, shield.event_dispatcher = None, None
        shield.blacklist = BlacklistManager(root / "empty-blacklist.yaml")
        def current_window():
            if window[0] == "unknown":
                return None
            title = "Private browsing" if window[0] == "sensitive" else "Synthetic lecture notes"
            return WindowInfo(title, "firefox", 1, identity=window[0])
        shield.monitor = SimpleNamespace(get_active_window=current_window)
        async def capture():
            return Image.new("RGB", (160, 100), "white")
        sampler = SimpleNamespace(privacy_shield=shield, capture=capture, last_error="",
            get_active_window_title=lambda: "Synthetic lecture notes")
        skill = ScreenCaptureSkill()
        skill.set_sampler(sampler)
        skill.set_ocr(SimpleNamespace(extract_text=lambda image:
            "Voltage divider: Vin=12 V, R1=2 kohm, R2=2 kohm. Find Vout."))
        assistant.skill_registry.register(skill)
        assistant.screen_sampler = sampler
        for engine in (assistant.llm, assistant.semantic.llm):
            original = engine._create
            async def record(_original=original, **kwargs):
                prompts.append("\n".join(item.get("content", "") for item in kwargs["messages"]
                                         if item["role"] == "system"))
                return await _original(**kwargs)
            engine._create = record
        return assistant

    error = None
    try:
        blob = open_assistant()
        for index, turn in enumerate(scenario.turns):
            if turn.restart:
                await close_assistant(blob)
                blob = open_assistant()
            if turn.window:
                window[0] = turn.window
            attachments = []
            if turn.attach:
                source = root / "synthetic-study-brief.pdf"
                make_pdf(source, ["Project Cobalt study brief: HDL state machines and IoT sensors."])
                attachments = [str(source)]
            before_tools, before_calls, before_prompts = len(blob.skill_registry.history), len(calls), len(prompts)
            started = time.monotonic()
            try:
                with redirect_stdout(StringIO()):
                    answer = await asyncio.wait_for(blob.handle_user_message(pb.UserMessage(
                        text=turn.request, attachments=attachments)), timeout=110)
                receipts = list(blob.skill_registry.history)[before_tools:]
                checks, skipped = response_checks(turn, answer, receipts, calls[before_calls:],
                                                  prompts[before_prompts:], live=live)
                entry = {"turn": index + 1, "request": turn.request, "answer": answer,
                    "tools": receipts, "checks": checks, "model_answer_check_skipped": skipped,
                    "model_calls": len(calls) - before_calls, "seconds": round(time.monotonic() - started, 3),
                    "passed": all(checks.values())}
            except Exception as exc:
                error = type(exc).__name__
                entry = {"turn": index + 1, "request": turn.request, "passed": False, "error": error}
            turns.append(entry)
            print(f"SWEEP {runtime}/{scenario.name}/{index + 1}: {'PASS' if entry['passed'] else 'FAIL'}", flush=True)
            if error:
                break
    except Exception as exc:
        error = type(exc).__name__
    finally:
        if blob is not None:
            try:
                await close_assistant(blob)
            except Exception as exc:
                error = error or type(exc).__name__
        for system in set(systems):
            system.stop()
            # Remove only this scenario's stopped clients. Chroma's Rust stop
            # is not idempotent; the surrounding test process may also clean up.
            from chromadb.api.shared_system_client import SharedSystemClient
            for identifier, registered in list(SharedSystemClient._identifier_to_system.items()):
                if registered is system:
                    del SharedSystemClient._identifier_to_system[identifier]
    return {"case": scenario.name, "runtime_requested": runtime,
            "runtime": blob.config.agent_runtime if blob is not None else runtime,
            "model": blob.config.model_name if blob is not None else None,
            "transport": blob.config.hermes_transport if blob is not None else None,
            "turns": turns, "model_calls": calls,
            "error": error, "passed": error is None and len(turns) == len(scenario.turns) and all(t["passed"] for t in turns)}


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


async def run(*, live=False, runtime="classic", max_calls=80, cases=None, report_path=None):
    selected = [case for case in catalog() if cases is None or case.name in cases]
    if not selected or (cases is not None and set(cases) - {case.name for case in selected}):
        raise ValueError("Select existing conversation cases")
    if max_calls < 1:
        raise ValueError("max_calls must be positive")
    if live:
        from blob.config import BlobConfig
        from blob.privacy.controls import PrivacyControls
        PrivacyControls(BlobConfig.load().privacy_settings_path).check(cloud=True)
    budget = [max_calls]
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "live": live,
        "scope": "Synthetic conversations, disposable stores, fixture web and sensors; no real desktop or camera access.",
        "semantic_checks": "real provider answers" if live else "skipped; offline verifies host behavior only",
        "complete": False, "passed": False, "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="blob-conversation-sweep-") as temporary:
        for mode in (("classic", "configured") if runtime == "both" else (runtime,)):
            for case in selected:
                report["scenarios"].append(await evaluate(Path(temporary) / mode / case.name, case, mode,
                                                          live=live, budget=budget))
                if report_path:
                    write_report(report_path, report)
    results = report["scenarios"]
    report["passed"] = all(case["passed"] for case in results)
    report["complete"] = True
    report["counts"] = {"conversations": len(results), "passed": sum(c["passed"] for c in results),
        "turns": sum(len(c["turns"]) for c in results), "model_requests": max_calls - budget[0],
        "provider_calls": max_calls - budget[0] if live else 0,
        "failed_turns": sum(not t["passed"] for c in results for t in c["turns"])}
    if report_path:
        write_report(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runtime", choices=("classic", "configured", "both"), default="classic")
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--case", choices=[case.name for case in catalog()], action="append")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(live=args.live, runtime=args.runtime, max_calls=args.max_calls,
                             cases=args.case, report_path=args.report))
    print(json.dumps({"passed": report["passed"], **report["counts"]}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
