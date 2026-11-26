"""The source registry: every adapter the scheduler knows about.

To add a source: write an adapter, add it to `build_registry`, add a row to docs/sources.md. A source can be
switched off at runtime with `python -m app.cli disable-source <key>` (hides its vacancies, FR-26).
"""

from __future__ import annotations

from app.ingest.adapters.base import Adapter, FetchContext
from app.ingest.adapters.hh import HeadHunterAdapter
from app.ingest.adapters.seed_file import SeedFileAdapter
from app.ingest.adapters.wordpress import WordPressJobsAdapter
from app.ingest.settings import IngestSettings, get_ingest_settings


def build_registry(settings: IngestSettings | None = None) -> dict[str, Adapter]:
    s = settings or get_ingest_settings()
    adapters: list[Adapter] = [
        SeedFileAdapter(s.seed_path),
        HeadHunterAdapter(s),
        WordPressJobsAdapter(
            key="indrive_careers",
            name="inDrive Careers (careers.indrive.com)",
            base_url="https://careers.indrive.com",
            rest_base="open_position",
            employer="inDrive",
            policy_notes=(
                "Employer's own career site; robots.txt allows all agents (checked 2026-11-26). Read through the "
                "public WordPress REST API, Kazakhstan postings only, every 12 h, 1 request/s."
            ),
        ),
    ]
    return {a.key: a for a in adapters}


__all__ = ["Adapter", "FetchContext", "build_registry"]
