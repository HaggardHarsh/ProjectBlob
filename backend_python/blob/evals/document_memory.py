"""Evaluate real document-memory restarts; optionally use the configured cloud model.

Run: venv/bin/python -m blob.evals.document_memory --live
Only synthetic PDF content and user statements are sent to the provider.
"""

import argparse
import asyncio
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace

from blob.ai.orchestrator import BlobOrchestrator
from blob.config import BlobConfig
from blob.ipc import blob_service_pb2
from blob.memory.vector_store import VectorStore
from blob.skills.registry import SkillRegistry

SUBJECTS = "Dude my subjects are hdl,iot,probability,aptitude,signals,analog and drone tech."
PAGES = [
    "Monday 05.10.2026 CSE: CSE 207 Digital Electronics 9:30-10:30 am; CSE 203 Discrete Mathematics 2:30-3:30 pm.",
    "Monday 05.10.2026 ECE: ECE 201 Digital Design with HDL 9:30-10:30 am; ECE 211 Internet of Things 2:30-3:30 pm.",
    "Tuesday: Probability, Aptitude. Wednesday: Signals. Thursday: Analog and Drone Technology.",
]


class OfflineEmbedding:
    """Deterministic vectors with deliberately poor similarity for Monday questions."""
    def __call__(self, input):
        return [[100.0 if "monday" in text.casefold() else 0.0, 1.0] for text in input]

    def embed_query(self, input):
        return self(input)

    @staticmethod
    def name():
        return "document-memory-eval"

    def is_legacy(self):
        return False

    def default_space(self):
        return "l2"

    def supported_spaces(self):
        return ["l2"]

    def get_config(self):
        return {}

    @classmethod
    def build_from_config(cls, config):
        return cls()


def make_pdf(path, pages=PAGES):
    """Build a tiny valid PDF with a text layer without another PDF dependency."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for text in pages:
        page_ids.append(len(objects) + 1)
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = ("BT /F1 10 Tf 30 100 Td (" + safe + ") Tj ET").encode("ascii")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1200 180] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects) + 2} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects[1] = b"<< /Type /Pages /Kids [" + " ".join(f"{i} 0 R" for i in page_ids).encode() + b"] /Count " + str(len(pages)).encode() + b" >>"
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(output)


async def discard_event(event):
    pass


def make_blob(root, *, live=False, model=None, max_bytes=32000, vision="off"):
    config = BlobConfig.load()
    config.memory_db_path = str(root / "memory")
    config.documents_dir_path = str(root / "documents")
    config.skills_dir_path = str(root / "skills")
    config.vision_model_name = vision if live else "off"
    config.max_prompt_bytes = max_bytes
    if model:
        config.model_name = model
    if not live:
        config.nebius_api_key = "offline-evaluation"
    store = VectorStore(config.memory_db_path, embedding_function=OfflineEmbedding())
    blob = BlobOrchestrator(config, store, SkillRegistry(root / "skills"), SimpleNamespace(broadcast=discard_event))
    if not live:
        blob._streaming_disabled = True
        async def reply(messages, system_prompt):
            return SimpleNamespace(content="An offline analysis. <emote>IDLE</emote>")
        blob.llm.generate_from_messages = reply
    return blob


def check_exam_answer(answer, expected):
    """Check selected exam rows, allowing an explanation of excluded PDF rows."""
    lowered = answer.casefold()
    rows = "\n".join(line for line in lowered.splitlines()
                     if re.match(r"\s*(?:[-*]|\d+[.)]|\|)", line))
    selected = rows or lowered
    if expected == "ece":
        passed = (bool(re.search(r"\bhdl\b|digital design", selected)) and
                  bool(re.search(r"\biot\b|internet of things", selected)) and
                  "discrete mathematics" not in selected and "digital electronics" not in selected)
    elif expected == "cse":
        passed = "digital electronics" in selected and "discrete mathematics" in selected and "internet of things" not in selected
    else:
        passed = bool(re.search(r"(?:no|none|nothing|don't|do not|don’t|aren't|are not|isn't|is not).{0,100}(?:exam|paper|subject|course|monday)", lowered, re.S))
        passed = passed and not re.search(r"digital electronics|discrete mathematics|internet of things|\bhdl\b|drone", rows)
    # Reject a conflicting affirmative claim even if a later caveat is accurate.
    for sentence in re.split(r"(?<=[.!?])\s+|\n", lowered):
        if re.search(r"\byou (?:have|have got|'ve got)\b", sentence):
            excluded = (r"digital electronics|discrete mathematics" if expected == "ece" else
                        r"internet of things|\bhdl\b" if expected == "cse" else
                        r"digital electronics|discrete mathematics|internet of things|\bhdl\b")
            if re.search(excluded, sentence):
                passed = False
    return bool(passed and not re.search(r"(?:which|tell me your|need your).{0,35}(?:branch|program)", lowered))


async def run_evaluation(root, *, live=False, model=None, vision="off"):
    path = root / "synthetic_exam_schedule.pdf"
    make_pdf(path)
    first = make_blob(root, live=False, model=model)
    # Seed through the real attachment-reader/store paths with an offline answer.
    provider = first.llm.generate_from_messages
    streaming_disabled = first._streaming_disabled
    async def seed_reply(messages, system_prompt):
        return SimpleNamespace(content="You're CSE. <emote>HAPPY</emote>")
    first.llm.generate_from_messages = seed_reply
    first._streaming_disabled = True
    await first.handle_attachment_drop([str(path)])
    await first.handle_user_message(blob_service_pb2.UserMessage(text=SUBJECTS))
    first.llm.generate_from_messages = provider
    first._streaming_disabled = streaming_disabled
    path.unlink()
    outputs = []
    cases = [
        ("restart_before_consolidation", None, "ece"),
        ("new_subject_list_supersedes_old", "My subjects are Digital Electronics and Discrete Mathematics. I am in CSE.", "cse"),
        ("reassert_subjects_after_correction", "My subjects are now HDL and IoT. I am in ECE.", "ece"),
        ("subjects_override_conflicting_branch", "I am in CSE. My subjects are now HDL and IoT.", "ece"),
        ("no_monday_exam_for_current_subjects", "My subjects are now Probability and Analog.", "none"),
    ]
    for name, correction, expected in cases:
        if correction:
            change = make_blob(root, live=False, model=model)
            await change.handle_user_message(blob_service_pb2.UserMessage(text=correction))
        restarted = make_blob(root, live=live, model=model, vision=vision)
        answer = await restarted.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
        context = restarted.semantic.document_context("Monday")
        if live:
            passed = check_exam_answer(answer, expected)
        else:
            passed = (("hdl" in context.casefold()) if expected == "ece" else
                      ("Discrete Mathematics" in context) if expected == "cse" else
                      ("Probability and Analog" in context and "hdl" not in context.casefold()))
        outputs.append({"case": name, "passed": bool(passed), "answer": answer, "saved_context": context})
        print(f"EVAL {name}: {'PASS' if passed else 'FAIL'}", flush=True)
    # No user-specific evidence: fabricated old assistant output must not become a profile.
    unknown_root = root / "unknown_user"
    unknown_root.mkdir()
    unknown_path = unknown_root / "synthetic_exam_schedule.pdf"
    make_pdf(unknown_path)
    unknown = make_blob(unknown_root, live=False, model=model)
    await unknown.handle_attachment_drop([str(unknown_path)])
    unknown.episodic.add_episode("Thanks", "You are CSE and have Digital Electronics and Discrete Mathematics.")
    unknown = make_blob(unknown_root, live=live, model=model, vision=vision)
    answer = await unknown.handle_user_message(blob_service_pb2.UserMessage(text="What exam do I have on Monday?"))
    passed = (not unknown.semantic.document_context("Monday")) if not live else bool(
        re.search(r"(?:which|what|tell|need|share|know|confirm).{0,100}(?:subjects?|courses?|branch|program)", answer.casefold(), re.S))
    outputs.append({"case": "no_profile_no_branch_guess", "passed": passed, "answer": answer})
    print(f"EVAL no_profile_no_branch_guess: {'PASS' if passed else 'FAIL'}", flush=True)
    return {"mode": "live" if live else "offline", "model": first.config.model_name,
            "vision": vision if live else "off", "results": outputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--vision", default="auto", help="auto (normal attachment path), off, or an exact image model")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="blob-memory-eval-") as directory:
        report = asyncio.run(run_evaluation(Path(directory), live=args.live, model=args.model, vision=args.vision))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"mode": report["mode"], "model": report["model"], "vision": report["vision"],
                      "passed": sum(result["passed"] for result in report["results"]), "total": len(report["results"])}))
    raise SystemExit(0 if all(result["passed"] for result in report["results"]) else 1)


if __name__ == "__main__":
    main()
