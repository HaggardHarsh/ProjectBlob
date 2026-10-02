from blob.config import BlobConfig


def test_chat_model_default_can_be_overridden(tmp_path, monkeypatch):
    assert BlobConfig().model_name == "Qwen/Qwen3-30B-A3B-Instruct-2507"

    monkeypatch.setenv("BLOB_MODEL_NAME", "nvidia/Nemotron-3_5-Lightning")
    config = BlobConfig.load(str(tmp_path / "missing.yaml"))

    assert config.model_name == "nvidia/Nemotron-3_5-Lightning"


def test_prompt_byte_budget_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_MAX_PROMPT_BYTES", "12000")

    assert BlobConfig.load(str(tmp_path / "missing.yaml")).max_prompt_bytes == 12000


def test_reminder_database_path_can_be_overridden(tmp_path, monkeypatch):
    path = tmp_path / "reminders.sqlite3"
    monkeypatch.setenv("BLOB_REMINDERS_DB_PATH", str(path))
    assert BlobConfig.load(str(tmp_path / "missing.yaml")).reminders_db_path == str(path.resolve())


def test_document_library_path_can_be_overridden(tmp_path, monkeypatch):
    path = tmp_path / "documents"
    monkeypatch.setenv("BLOB_DOCUMENTS_DIR_PATH", str(path))
    assert BlobConfig.load(str(tmp_path / "missing.yaml")).documents_dir_path == str(path.resolve())
