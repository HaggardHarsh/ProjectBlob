import hashlib
import chromadb
import pytest

from blob.memory.migrate_legacy import migrate, validate_facts
from blob.memory.semantic import _sentence_key
from blob.memory.vector_store import VectorStore


def test_migration_keeps_episodes_and_only_reviewed_user_sentences(tmp_path):
    db_path = tmp_path / "chroma_db"
    store = VectorStore(str(db_path))
    store.store("User: I collect postcards. Today is Thursday.\nBlob: Great!",
                {"type": "episodic", "consolidated": True})
    store.store("User: I prefer Rust.\nBlob: You prefer Python.",
                {"type": "episodic", "consolidated": False})
    store.store("You prefer Python", {"type": "semantic"}, collection="semantic")
    selected_id = hashlib.sha256(_sentence_key("I prefer Rust.").encode("utf-8")).hexdigest()
    store.store("Old incorrect Rust summary", {"type": "semantic"},
                collection="semantic", memory_id=selected_id)
    store.store("I collect postcards.", {"type": "semantic", "grounded": True}, collection="semantic")

    with pytest.raises(ValueError, match="eligible exact user sentence"):
        validate_facts(["You prefer Python."], store.episodic.get(include=["documents", "metadatas"]))

    backup_path, removed, selected = migrate(db_path, ["I collect postcards.", "I prefer Rust."])

    assert (removed, selected) == (2, 2)
    assert backup_path is not None and (backup_path / "chroma.sqlite3").is_file()
    backup = chromadb.PersistentClient(path=str(backup_path))
    assert backup.get_collection("semantic").count() == 3
    assert backup.get_collection("episodic").count() == 2
    actual = store.semantic.get(include=["documents", "metadatas"])
    assert set(actual["documents"]) == {"I collect postcards.", "I prefer Rust."}
    assert len(actual["documents"]) == 2
    assert all(meta["grounded"] is True for meta in actual["metadatas"])
    assert store.episodic.count() == 2
    assert all(meta["consolidated"] for meta in store.episodic.get(include=["metadatas"])["metadatas"])
    assert migrate(db_path, ["I collect postcards.", "I prefer Rust."]) == (None, 0, 0)
