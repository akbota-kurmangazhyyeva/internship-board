"""Settings for source collection (Part B). Read from environment variables, like app.config."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Identify ourselves honestly to every source (HeadHunter requires a contact in the User-Agent).
    http_user_agent: str = "InternshipBoardKZ/0.1 (NU senior project; contact: team26@nu.edu.kz)"
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3  # inside one run, for 429 / 5xx / network errors
    http_min_interval_seconds: float = 1.0  # politeness delay between requests to the same host

    # Raw HTTP responses, gzip-compressed, for audit and replay (kickoff: "object storage for raw snapshots").
    snapshot_dir: Path = Path("data/snapshots")

    # Seed dataset (JSONL, one RawPostingIn per line).
    seed_path: Path = Path("data/seed/postings.jsonl")

    # HeadHunter. Since 2026 hh.ru answers 403 to anonymous /vacancies requests: an application token from
    # dev.hh.ru is required. Without it the hh_kz source stays registered but every run fails with a clear message.
    hh_app_token: str | None = None
    # Placeholder until the token is approved: with no token, hh_kz loads these demo postings (clearly labelled).
    hh_stub_path: Path = Path("data/hh_stub/vacancies.json")
    hh_area: str = "40"  # Kazakhstan
    hh_search_text: str = "стажер OR стажёр OR стажировка OR intern OR internship OR junior OR тағылымдама"
    hh_max_pages: int = 10  # x 100 per page; hh never returns more than 2000 results per query

    # Scheduler (Celery + Redis).
    redis_url: str = "redis://localhost:6379/0"
    collect_max_retries: int = 3  # whole-run retries after a transient failure, with exponential backoff
    collect_retry_base_seconds: int = 60


@lru_cache
def get_ingest_settings() -> IngestSettings:
    return IngestSettings()
