"""Runtime configuration. Secret values are never returned by the API."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTORO_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "local"
    data_dir: Path = Field(default=REPO_ROOT / "backend" / "data" / "runtime")
    database_url: str = ""
    mongo_db: str = "autoro"
    provider: str = "demo"
    teacher_provider: str = "deterministic_demo"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:1b"
    ollama_timeout_seconds: float = 60.0
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    openai_compat_model: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    max_extract_chars: int = 8000
    max_question_chars: int = 1000
    rate_limit_per_minute: int = 60
    jobs_inline: bool = False
    retrieval_mode: str = "hybrid"
    bm25_min_score: float = 0.15
    max_synthetic_count: int = 20
    nhtsa_max_records: int = 50
    nhtsa_timeout_seconds: float = 30.0
    download_max_bytes: int = 30_000_000
    split_seed: int = 42
    app_name: str = "AutoRO-LM"
    mlx_model: str = "mlx-community/Llama-3.2-1B-Instruct-4bit"
    mlx_adapter_dir: str = ""
    mlx_lora_layers: int = 8
    mlx_lora_rank: int = 8
    mlx_learning_rate: float = 1e-5
    mlx_batch_size: int = 1
    mlx_iters: int = 20
    mlx_seed: int = 42

    @property
    def resolved_adapter_dir(self) -> Path:
        if self.mlx_adapter_dir:
            return Path(self.mlx_adapter_dir)
        return self.data_dir / "adapters" / "current"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "autoro.sqlite3"

    @property
    def demo_dir(self) -> Path:
        return REPO_ROOT / "backend" / "data" / "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
