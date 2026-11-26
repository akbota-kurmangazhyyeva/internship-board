"""What every source adapter looks like.

An adapter knows one source. It turns that source's data into `RawPostingIn` objects and nothing more:
storage, extraction, duplicates and lifecycle all happen in the pipeline (Part A).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from app.ingest.contract import RawPostingIn
from app.ingest.http import PoliteClient


@dataclass
class FetchContext:
    client: PoliteClient
    since: datetime | None = None  # start of the last successful run, for incremental sources
    limit: int | None = None  # stop after this many postings (seed collection, smoke tests)
    complete: bool = field(default=False)  # the adapter sets this when it saw every current posting


class Adapter(ABC):
    key: str  # stable source key stored in `sources.key`
    name: str  # human-readable
    kind: str  # api | feed | page | telegram | file | manual
    base_url: str | None = None
    interval_minutes: int = 360
    # True if one run sees *every* live posting, so a posting missing from a complete run has been removed (FR-11).
    full_scan: bool = False
    # Shown in the admin view and the policy matrix (docs/sources.md).
    policy_notes: str = ""

    @abstractmethod
    def fetch(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        """Yield postings. Raise TransientError / PermanentError on failure."""

    def check_config(self) -> None:  # noqa: B027 - optional hook
        """Raise PermanentError if the adapter can't run (missing token, missing file)."""
