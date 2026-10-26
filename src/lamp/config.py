"""App settings, loaded from the environment and `.env`."""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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
    static_dir: Path = Path(__file__).resolve().parents[2] / "web" / "static"
    dev_noauth: bool = False  # LAMP_DEV_NOAUTH-style escape hatch for screenshots; never in .env

    max_updates_per_sec: float = 10.0
    sync_offset_ms: int = 0

    @field_validator("app_password")
    @classmethod
    def _password_set(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("APP_PASSWORD must not be empty")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
