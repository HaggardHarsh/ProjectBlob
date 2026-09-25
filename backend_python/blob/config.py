import os
import yaml
from pydantic import BaseModel, Field

class BlobConfig(BaseModel):
    ipc_address: str = Field(default="localhost:50051")
    model_name: str = Field(default="nvidia/Llama-3.1-Nemotron-70B-Instruct-HF") # NVIDIA Open Source Model
    nebius_api_key: str = Field(default=os.environ.get("NEBIUS_API_KEY", ""))
    nebius_base_url: str = Field(default="https://api.studio.nebius.ai/v1")
    memory_db_path: str = Field(default="./data/chroma_db")
    blacklist_path: str = Field(default="./data/blacklist.yaml")
    personality_path: str = Field(default="./data/blob_personality.yaml")
    screen_sample_interval_sec: int = Field(default=30)
    screen_capture_mode: str = Field(default="active_window") # "full_screen" or "active_window"
    privacy_poll_interval_ms: int = Field(default=500)
    energy_decay_rate: float = Field(default=0.01)

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "BlobConfig":
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()
