import os
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class BlobConfig(BaseModel):
    ipc_address: str = Field(default="localhost:50051")
    ipc_token_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/ipc.token"))
    privacy_settings_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/privacy.json"))
    model_name: str = Field(default="zai-org/GLM-5.3-Flash")
    memory_model_name: str = Field(default="nvidia/Nemotron-3_5-Lightning", min_length=1)
    nebius_api_key: str = Field(default=os.environ.get("NEBIUS_API_KEY", ""))
    nebius_base_url: str = Field(default="https://api.studio.nebius.ai/v1")
    max_prompt_bytes: int = Field(default=32000, ge=4096)
    vision_model_name: str = "auto"  # Discover an available image-input model; "off" uses OCR only.
    memory_db_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/memory/chromadb"))
    blacklist_path: str = Field(default_factory=lambda: str(Path(__file__).resolve().parents[1] / "data/blacklist.yaml"))
    personality_path: str = Field(default_factory=lambda: str(Path(__file__).resolve().parents[1] / "data/blob_personality.yaml"))
    camera_enabled: bool = True
    camera_device_index: int = 0
    face_db_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/faces"))
    skills_dir_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/skills"))
    reminders_db_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/reminders.sqlite3"))
    documents_dir_path: str = Field(default_factory=lambda: str(Path.home() / ".blob/documents"))
    screen_sample_interval_sec: int = Field(default=30)
    screen_capture_mode: str = Field(default="active_window") # "full_screen" or "active_window"
    privacy_poll_interval_ms: int = Field(default=500)
    energy_decay_rate: float = Field(default=0.01)

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "BlobConfig":
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        if "memory_db_path" not in data and "BLOB_MEMORY_DB_PATH" not in os.environ:
            # Keep installations that used the original working-directory path readable.
            legacy = Path(__file__).resolve().parents[1] / "data/chroma_db"
            if legacy.exists() and any(legacy.iterdir()):
                data["memory_db_path"] = str(legacy)
        if "BLOB_MEMORY_DB_PATH" in os.environ:
            data["memory_db_path"] = os.environ["BLOB_MEMORY_DB_PATH"]
        if "BLOB_MODEL_NAME" in os.environ:
            data["model_name"] = os.environ["BLOB_MODEL_NAME"]
        if "BLOB_MEMORY_MODEL_NAME" in os.environ:
            data["memory_model_name"] = os.environ["BLOB_MEMORY_MODEL_NAME"]
        for variable, field in (("BLOB_IPC_ADDRESS", "ipc_address"), ("BLOB_IPC_TOKEN_PATH", "ipc_token_path"),
                                ("BLOB_PRIVACY_SETTINGS_PATH", "privacy_settings_path")):
            if variable in os.environ:
                data[field] = os.environ[variable]
        if "BLOB_MAX_PROMPT_BYTES" in os.environ:
            data["max_prompt_bytes"] = int(os.environ["BLOB_MAX_PROMPT_BYTES"])
        if "BLOB_VISION_MODEL" in os.environ:
            data["vision_model_name"] = os.environ["BLOB_VISION_MODEL"]
        if "BLOB_CAMERA_ENABLED" in os.environ:
            data["camera_enabled"] = os.environ["BLOB_CAMERA_ENABLED"].lower() in {"1", "true", "yes", "on"}
        if "BLOB_CAMERA_DEVICE_INDEX" in os.environ:
            data["camera_device_index"] = int(os.environ["BLOB_CAMERA_DEVICE_INDEX"])
        if "BLOB_FACE_DB_PATH" in os.environ:
            data["face_db_path"] = os.environ["BLOB_FACE_DB_PATH"]
        if "BLOB_SKILLS_DIR_PATH" in os.environ:
            data["skills_dir_path"] = os.environ["BLOB_SKILLS_DIR_PATH"]
        if "BLOB_REMINDERS_DB_PATH" in os.environ:
            data["reminders_db_path"] = os.environ["BLOB_REMINDERS_DB_PATH"]
        if "BLOB_DOCUMENTS_DIR_PATH" in os.environ:
            data["documents_dir_path"] = os.environ["BLOB_DOCUMENTS_DIR_PATH"]
        config = cls(**data)
        config.memory_db_path = str(Path(config.memory_db_path).expanduser().resolve())
        config.face_db_path = str(Path(config.face_db_path).expanduser().resolve())
        config.skills_dir_path = str(Path(config.skills_dir_path).expanduser().resolve())
        config.reminders_db_path = str(Path(config.reminders_db_path).expanduser().resolve())
        config.documents_dir_path = str(Path(config.documents_dir_path).expanduser().resolve())
        return config
