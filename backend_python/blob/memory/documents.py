"""Private source copies for document recall, separate from personal facts."""

from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time

MAX_DOCUMENTS = 20
MAX_LIBRARY_BYTES = 200 * 1024 * 1024
MAX_SOURCE_BYTES = 20 * 1024 * 1024
STOP_WORDS = frozenset("a an and are about again before blob can could did do does earlier explain for from give have how i in is it me my now of on please remember shared show tell that the this to was what when which with would you your time".split())
ALIASES = {"exams": "exam", "timetables": "schedule", "timetable": "schedule", "schedules": "schedule",
           "pdfs": "pdf", "documents": "document", "attachments": "attachment", "pictures": "picture", "images": "image",
           "files": "file", "pages": "page", "photo": "image", "photos": "image"}
DOCUMENT_REFERENCE = re.compile(r"\b(?:pdfs?|documents?|attachments?|files?|timetables?|schedules?|images?|pictures?|photos?)\b", re.I)


class DocumentError(ValueError):
    pass


def _terms(text):
    return {ALIASES.get(word, word) for word in re.findall(r"[^\W_]+", text.casefold())
            if 2 <= len(word) <= 100 and word not in STOP_WORDS and not word.isdigit()}


class DocumentLibrary:
    def __init__(self, directory=None):
        self.root = Path(directory).expanduser().resolve() if directory is not None else None
        self._lock = threading.RLock()

    @property
    def enabled(self):
        return self.root is not None

    def _connect(self):
        connection = sqlite3.connect(str(self.root / "index.sqlite3"))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    def _initialize(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, original_path TEXT UNIQUE NOT NULL,
                sha256 TEXT NOT NULL, size INTEGER NOT NULL, search_text TEXT NOT NULL, saved_at REAL NOT NULL)""")
        os.chmod(self.root / "index.sqlite3", 0o600)

    def records(self):
        if not self.enabled or not (self.root / "index.sqlite3").is_file():
            return []
        with self._lock:
            try:
                with closing(self._connect()) as db:
                    return [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY saved_at DESC, id")]
            except sqlite3.Error as exc:
                raise DocumentError("I couldn't read the saved document index. Check BLOB_DOCUMENTS_DIR_PATH and the backend logs.") from exc

    def path_for(self, record):
        # Index contents must not be able to escape the private library directory.
        if (not re.fullmatch(r"[a-f0-9]{16}", record["id"]) or
                record["name"] in {"", ".", ".."} or Path(record["name"]).name != record["name"]):
            raise DocumentError("The saved document index contains an invalid file reference.")
        path = self.root / record["id"] / record["name"]
        if path.parent.is_symlink():
            raise DocumentError("The saved document folder has changed. Check the document library.")
        return path

    def original_path(self, path):
        resolved = str(Path(path).resolve())
        for record in self.records():
            if resolved == str(self.path_for(record)):
                return record["original_path"]
        return resolved

    def remember(self, sources):
        if not self.enabled:
            return False
        with self._lock:
            self._initialize()
            existing = self.records()
            cached = {str(self.path_for(record)) for record in existing}
            incoming = [source for source in sources if source.path not in cached]
            if not incoming:
                return False
            by_original = {record["original_path"]: record for record in existing}
            candidates = dict(by_original)
            for source in incoming:
                if len(source.data) > MAX_SOURCE_BYTES:
                    raise DocumentError("A file exceeds the saved document size limit.")
                digest = hashlib.sha256(source.data).hexdigest()
                identifier = hashlib.sha256((source.path + "\0" + digest).encode()).hexdigest()[:16]
                previous = by_original.get(source.path)
                text = source.text
                if previous and previous["sha256"] == digest:
                    text = previous["search_text"] + "\n" + text
                candidates[source.path] = {"id": identifier, "name": Path(source.path).name,
                    "original_path": source.path, "sha256": digest, "size": len(source.data),
                    "search_text": text.encode("utf-8")[:32000].decode("utf-8", errors="ignore"), "saved_at": time.time()}
            if len(candidates) > MAX_DOCUMENTS or sum(item["size"] for item in candidates.values()) > MAX_LIBRARY_BYTES:
                raise DocumentError("Saved documents are full (20 files / 200 MB). Use /files saved and /files forget <id> to free space.")
            created = []
            try:
                for source in incoming:
                    record = candidates[source.path]
                    destination = self.path_for(record)
                    destination.parent.mkdir(mode=0o700, exist_ok=True)
                    if str(destination) not in cached:
                        created.append(destination)
                    temporary_path = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".document-", delete=False) as temporary:
                            temporary_path = Path(temporary.name)
                            temporary.write(source.data)
                        os.chmod(temporary_path, 0o600)
                        temporary_path.replace(destination)
                    finally:
                        if temporary_path is not None:
                            temporary_path.unlink(missing_ok=True)
                with closing(self._connect()) as db, db:
                    for source in incoming:
                        record = candidates[source.path]
                        db.execute("DELETE FROM documents WHERE original_path = ?", (source.path,))
                        db.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(record.values()))
            except (OSError, sqlite3.Error):
                # Preserve previous records and remove copies that were never indexed.
                for destination in created:
                    try:
                        destination.unlink(missing_ok=True)
                        destination.parent.rmdir()
                    except OSError:
                        pass
                raise
            for source in incoming:
                old = by_original.get(source.path)
                if old and old["id"] != candidates[source.path]["id"]:
                    self.path_for(old).unlink(missing_ok=True)
                    try:
                        self.path_for(old).parent.rmdir()
                    except OSError:
                        pass  # A leftover temporary file must not invalidate a committed save.
            return True

    def find(self, question):
        terms = _terms(question) - {"pdf", "document", "attachment", "file", "image", "picture", "page"}
        ranked = []
        records = self.records()
        for record in records:
            name_terms = _terms(record["name"])
            body_terms = _terms(record["search_text"])
            score = 4 * len(terms & name_terms) + 2 * len(terms & body_terms)
            if score:
                ranked.append((score, record))
        if ranked:
            ranked.sort(key=lambda item: (-item[0], -item[1]["saved_at"]))
            return [record for _, record in ranked[:4]]
        if DOCUMENT_REFERENCE.search(question) and len(records) == 1:
            return records
        return []

    def reopen(self, records):
        paths = []
        for record in records:
            path = self.path_for(record)
            try:
                if path.is_symlink() or path.parent.is_symlink():
                    raise OSError("Invalid saved source")
                with path.open("rb") as handle:
                    data = handle.read(MAX_SOURCE_BYTES + 1)
                if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                    raise OSError("Saved source changed")
            except OSError as exc:
                raise DocumentError(f"The saved copy of {record['name']} is missing or changed. Drop that file again to restore it.") from exc
            paths.append(str(path))
        return paths

    def forget(self, identifier):
        with self._lock:
            records = self.records()
            selected = records if identifier == "all" else [record for record in records if record["id"] == identifier]
            if not selected:
                raise DocumentError("No saved document with that ID. Use /files saved to list IDs.")
            for record in selected:
                path = self.path_for(record)
                path.unlink(missing_ok=True)
                if path.parent.exists():
                    try:
                        path.parent.rmdir()
                    except OSError:
                        pass
            with closing(self._connect()) as db, db:
                db.executemany("DELETE FROM documents WHERE id = ?", [(record["id"],) for record in selected])
            return selected
