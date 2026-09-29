"""Replace legacy semantic summaries with reviewed, verbatim user memories.

Run while Blob is stopped. The facts file is a JSON array of sentences copied
exactly from the user's side of saved episodes. A complete database backup is
made before any memory is changed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

from blob.config import BlobConfig
from blob.memory.semantic import _sentence_key, _user_sentences
from blob.memory.vector_store import VectorStore


def source_sentences(episodes: dict) -> set[str]:
    messages = []
    for document in episodes["documents"]:
        if document.startswith("User: "):
            messages.append(document.split("\nBlob: ", 1)[0][6:])
    return set(_user_sentences(messages).values())


def validate_facts(facts: list[str], episodes: dict) -> list[str]:
    if not isinstance(facts, list) or any(not isinstance(fact, str) for fact in facts):
        raise ValueError("Facts file must be a JSON array of strings")
    allowed = source_sentences(episodes)
    if not allowed and facts:
        raise ValueError("No eligible original user sentences found")
    if len(facts) != len(set(facts)):
        raise ValueError("Facts file contains duplicate sentences")
    if len(facts) != len({_sentence_key(fact) for fact in facts}):
        raise ValueError("Facts file contains equivalent sentences")
    for fact in facts:
        if fact not in allowed:
            raise ValueError(f"Not an eligible exact user sentence: {fact!r}")
    return facts


def backup_database(db_path: Path) -> Path:
    backup_root = db_path.parent / "memory_backups"
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup_path = backup_root / f"{db_path.name}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    # A collision must fail instead of overwriting the only safe copy.
    shutil.copytree(db_path, backup_path)
    with sqlite3.connect(f"file:{backup_path / 'chroma.sqlite3'}?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Backup failed SQLite integrity check: {backup_path}")
    return backup_path


def migrate(db_path: Path, facts: list[str]) -> tuple[Path | None, int, int]:
    if not (db_path / "chroma.sqlite3").is_file():
        raise ValueError(f"No Chroma database at {db_path}")
    store = VectorStore(str(db_path))
    episodes = store.episodic.get(include=["documents", "metadatas"])
    facts = validate_facts(facts, episodes)
    semantic = store.semantic.get(include=["documents", "metadatas"])
    legacy_ids = [memory_id for memory_id, metadata in zip(semantic["ids"], semantic["metadatas"])
                  if (metadata or {}).get("grounded") is not True]
    grounded_texts = {document for document, metadata in zip(semantic["documents"], semantic["metadatas"])
                      if (metadata or {}).get("grounded") is True}
    replacement_ids = {hashlib.sha256(_sentence_key(fact).encode("utf-8")).hexdigest()
                       for fact in facts if fact not in grounded_texts}
    unconsolidated = [memory_id for memory_id, metadata in zip(episodes["ids"], episodes["metadatas"])
                      if not (metadata or {}).get("consolidated")]
    if not legacy_ids and not unconsolidated and all(fact in grounded_texts for fact in facts):
        return None, 0, 0

    backup_path = backup_database(db_path)
    try:
        for fact in facts:
            if fact in grounded_texts:
                continue
            memory_id = hashlib.sha256(_sentence_key(fact).encode("utf-8")).hexdigest()
            store.store(fact, {"type": "semantic", "pinned": True, "grounded": True},
                        collection="semantic", memory_id=memory_id)
        if legacy_ids:
            store.semantic.delete(ids=[memory_id for memory_id in legacy_ids
                                       if memory_id not in replacement_ids])
        if unconsolidated:
            by_id = {memory_id: (document, metadata) for memory_id, document, metadata in
                     zip(episodes["ids"], episodes["documents"], episodes["metadatas"])}
            store.mark_consolidated([
                {"id": memory_id, "text": by_id[memory_id][0], "metadata": by_id[memory_id][1]}
                for memory_id in unconsolidated
            ])
        actual = store.semantic.get(include=["documents", "metadatas"])
        if any((metadata or {}).get("grounded") is not True for metadata in actual["metadatas"]):
            raise RuntimeError("Legacy semantic memories remain after migration")
        if any(fact not in actual["documents"] for fact in facts):
            raise RuntimeError("A selected user sentence is missing after migration")
    except Exception as exc:
        raise RuntimeError(f"Migration failed; restore from {backup_path}") from exc
    return backup_path, len(legacy_ids), len(facts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts-file", required=True, type=Path,
                        help="JSON array of exact user sentences selected for long-term memory")
    parser.add_argument("--db-path", type=Path, default=Path(BlobConfig.load().memory_db_path))
    args = parser.parse_args()
    facts = json.loads(args.facts_file.read_text())
    backup_path, removed, retained = migrate(args.db_path.expanduser().resolve(), facts)
    if backup_path is None:
        print("Memory already migrated; no changes made")
    else:
        print(f"Backup: {backup_path}")
        print(f"Removed {removed} legacy semantic memories; retained {retained} reviewed user sentences")


if __name__ == "__main__":
    main()
