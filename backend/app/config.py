"""Runtime configuration, read from environment variables (and `.env` in development)."""

from datetime import timedelta, timezone
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Kazakhstan has used a single UTC+5 zone since March 2024 (DR-07).
KZ_TZ = timezone(timedelta(hours=5), name="Asia/Almaty")

_DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    database_url: str = "postgresql+psycopg://board:board@localhost:5432/board"
    secret_key: str = _DEV_SECRET
    access_token_minutes: int = 60 * 24 * 7
    cors_origins: list[str] = ["http://localhost:3000"]

    # Extraction: values below this confidence are shown as "Unknown" (FR-07).
    confidence_threshold: float = 0.6

    # Duplicate detection (FR-08/09). Tune on the DEV split only, never on the frozen test set.
    dedup_merge_threshold: float = 0.75
    dedup_review_threshold: float = 0.55
    dedup_window_days: int = 60

    # Lifecycle (FR-11): a vacancy whose every source page has been gone this long is expired.
    stale_after_days: int = 3

    @model_validator(mode="after")
    def _no_default_secret_in_prod(self) -> "Settings":
        if self.env == "prod" and self.secret_key == _DEV_SECRET:
            raise ValueError("SECRET_KEY must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
