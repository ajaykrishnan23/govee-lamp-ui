"""App settings, loaded from the environment and `.env`."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    app_password: str

    monthly_budget_usd: float = 10.0
    prompt_model: str = "gpt-6-luna"
    show_model: str = "gpt-6-luna"

    host: str = "0.0.0.0"
    port: int = 8443
    data_dir: Path = Path("data")
    certs_dir: Path = Path("certs")

    max_updates_per_sec: float = 10.0
    sync_offset_ms: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
