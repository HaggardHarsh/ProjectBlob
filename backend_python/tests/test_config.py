from blob.config import BlobConfig


def test_chat_model_default_can_be_overridden(tmp_path, monkeypatch):
    assert BlobConfig().model_name == "Qwen/Qwen3-30B-A3B-Instruct-2507"

    monkeypatch.setenv("BLOB_MODEL_NAME", "nvidia/Nemotron-3_5-Lightning")
    config = BlobConfig.load(str(tmp_path / "missing.yaml"))

    assert config.model_name == "nvidia/Nemotron-3_5-Lightning"


def test_prompt_byte_budget_can_be_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_MAX_PROMPT_BYTES", "12000")

    assert BlobConfig.load(str(tmp_path / "missing.yaml")).max_prompt_bytes == 12000
