"""Completed file answers kept independently of source files and user facts."""

from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time

from blob.memory.documents import _terms

MAX_RESULTS = 100
MAX_RESULT_BYTES = 128_000
MAX_TOTAL_BYTES = 2_000_000
REPLAY_REQUEST = re.compile(
    r"^(?:please\s+)?(?:show|repeat|display|bring back|give)(?:\s+me)?\s+"
    r"(?:(?:my|the|our|that|saved|previous|old|generated)\s+)*"
    r"(?P<kind>timetable|schedule|datesheet|notes|summary|plan|answer|result)(?:\s+(?:again|please))?[.!?]*$", re.I)
SOURCE_REQUEST = re.compile(r"\b(?:reread|re-read|reextract|re-extract|original|raw|page\s+\d+)\b", re.I)
EXAM_QUERY = re.compile(r"\b(?:exams?|papers?|mid[ -]?(?:sem|term)s?|timetable|datesheet)\b", re.I)
EDIT_REQUEST = re.compile(
    r"^\s*(?:(?:hey|bro|dude|actually)[,:\s]+)?"
    r"(?:(?:please|(?:can|could|would|will)\s+you)\s+)?"
    r"(?:change|update|revise|replace|move|reschedule|shorten|simplify|rewrite|convert)\b", re.I)


class ResultError(ValueError):
    pass


def result_kind(question, answer=""):
    creation = re.search(r"\b(?:make|create|build|prepare|generate|write|extract|organize|organise)\b", question, re.I)
    table = re.search(r"(?m)^\s*\|.+\|\s*$", answer)
    if re.search(r"\b(?:timetable|schedule|datesheet)\b", question, re.I) and (creation or table):
        return "timetable"
    if creation and re.search(r"\bnotes?\b", question, re.I):
        return "notes"
    if re.search(r"\b(?:summarize|summarise)\b", question, re.I) or (creation and re.search(r"\bsummary\b", question, re.I)):
        return "summary"
    if creation and re.search(r"\bplan\b", question, re.I):
        return "plan"
    return "answer"


class ResultLibrary:
    def __init__(self, directory=None):
        self.root = Path(directory).expanduser().resolve() if isinstance(directory, (str, os.PathLike)) else None
        self._lock = threading.RLock()

    def _connect(self):
        db = sqlite3.connect(str(self.root / "document_results.sqlite3"))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        return db

    def _initialize(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS results (
                id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
                kind TEXT NOT NULL, sources TEXT NOT NULL, user_context TEXT NOT NULL,
                saved_at REAL NOT NULL)""")
        os.chmod(self.root / "document_results.sqlite3", 0o600)

    @staticmethod
    def _record(row):
        record = dict(row)
        record["sources"] = json.loads(record["sources"])
        return record

    def records(self):
        if self.root is None or not (self.root / "document_results.sqlite3").is_file():
            return []
        try:
            with self._lock, closing(self._connect()) as db:
                return [self._record(row) for row in db.execute("SELECT * FROM results ORDER BY saved_at DESC, id")]
        except (sqlite3.Error, ValueError) as exc:
            raise ResultError("I couldn't read saved results. Check the memory directory and backend logs.") from exc

    def save(self, question, answer, sources, user_context="", *, kind=None, replace_id=None):
        if self.root is None:
            return None
        if len((question + answer + user_context).encode("utf-8")) > MAX_RESULT_BYTES:
            raise ResultError("That answer is too large to save. Ask for a shorter result before deleting its source.")
        kind = kind or result_kind(question, answer)
        # Regenerating a timetable from the same sources updates that work;
        # unrelated answers and different PDFs remain independent.
        scope = [kind, sorted(source["original_path"] for source in sources)]
        if kind == "timetable":
            scope.append(sorted(set(re.findall(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", question.casefold()))))
        if kind == "answer":
            scope.append(" ".join(question.casefold().split()))
        identifier = replace_id or hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:16]
        with self._lock:
            self._initialize()
            existing = [record for record in self.records() if record["id"] != identifier]
            if (len(existing) >= MAX_RESULTS or
                    sum(len((record["question"] + record["answer"] + record["user_context"]).encode("utf-8"))
                        for record in existing) + len((question + answer + user_context).encode("utf-8")) > MAX_TOTAL_BYTES):
                raise ResultError("Saved results are full. Use /results and /results forget <id> to free space.")
            record = {"id": identifier, "question": question, "answer": answer, "kind": kind,
                      "sources": sources, "user_context": user_context, "saved_at": time.time()}
            with closing(self._connect()) as db, db:
                db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (identifier, question, answer, kind, json.dumps(sources), user_context, record["saved_at"]))
            return record

    def get(self, identifier):
        return next((record for record in self.records() if record["id"] == identifier), None)

    def find(self, question, *, current_sources=()):
        if SOURCE_REQUEST.search(question):
            return []
        terms = _terms(question) - {"saved", "result", "results", "answer", "answers", "show", "make"}
        current = {record["original_path"]: record["sha256"] for record in current_sources}
        replay = REPLAY_REQUEST.fullmatch(question)
        requested_kind = replay.group("kind").casefold() if replay else None
        if requested_kind in {"schedule", "datesheet"}:
            requested_kind = "timetable"
        ranked = []
        for record in self.records():
            if requested_kind in {"timetable", "notes", "summary", "plan"} and record["kind"] != requested_kind:
                continue
            # A revised PDF wins over work made from its earlier version.
            if any(source["original_path"] in current and current[source["original_path"]] != source["sha256"]
                   for source in record["sources"]):
                continue
            names = " ".join(source["name"] for source in record["sources"])
            score = 3 * len(terms & _terms(record["question"] + " " + names)) + len(terms & _terms(record["answer"]))
            score += 4 * len(terms & _terms(record["kind"]))
            if EXAM_QUERY.search(question) and record["kind"] == "timetable":
                score += 4
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], -item[1]["saved_at"]))
        return [record for _, record in ranked[:3]]

    def forget(self, identifier):
        with self._lock:
            selected = [record for record in self.records() if identifier == "all" or record["id"] == identifier]
            if not selected:
                raise ResultError("No saved result with that ID. Use /results to list them.")
            with closing(self._connect()) as db, db:
                db.executemany("DELETE FROM results WHERE id = ?", [(record["id"],) for record in selected])
            return selected

    @staticmethod
    def context(question, records, max_bytes):
        """Bound excerpts while leaving complete saved answers intact on disk."""
        parts = []
        per_record = max_bytes // max(1, len(records))
        terms = _terms(question)
        for record in records:
            names = ", ".join(source["name"] for source in record["sources"])
            date = datetime.fromtimestamp(record["saved_at"]).astimezone().isoformat(timespec="minutes")
            header = (f"Saved generated {record['kind']} {record['id']} ({date}). Source names: {names}.\n"
                      f"Original request: {record['question']}\n")
            room = per_record - len(header.encode("utf-8")) - 80
            if room < 80:
                continue
            answer = record["answer"]
            if len(answer.encode("utf-8")) > room:
                lines = answer.splitlines(keepends=True)
                hits = [index for index, line in enumerate(lines) if terms & _terms(line)]
                start = max(0, hits[0] - 2) if hits else 0
                answer = "[Excerpt of saved result; other lines omitted]\n" + "".join(lines[start:]).encode("utf-8")[:room - 60].decode("utf-8", errors="ignore")
            parts.append(header + answer)
        return "\n\n".join(parts)
