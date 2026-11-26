"""Seed file adapter: postings collected by hand (or exported by `collect-seed`) as JSONL.

Used for the seed dataset of real postings, for sources we may read but not automate (Telegram channels,
LinkedIn posts the team copied manually with their URL), and for demos without network access.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from app.ingest.adapters.base import Adapter, FetchContext
from app.ingest.contract import RawPostingIn
from app.ingest.errors import PermanentError


class SeedFileAdapter(Adapter):
    kind = "file"
    interval_minutes = 24 * 60
    full_scan = False  # removing a line from the file must not silently expire a vacancy

    def __init__(self, path: Path, key: str = "seed_file", name: str = "Seed dataset (manual collection)") -> None:
        self.path = Path(path)
        self.key = key
        self.name = name
        self.policy_notes = (
            "Manually collected public postings with their original URL; used for evaluation and demos. "
            "Each line keeps the source in payload.collected_from."
        )
        self.errors: list[str] = []

    def check_config(self) -> None:
        if not self.path.exists():
            raise PermanentError(f"seed file {self.path} does not exist")

    def fetch(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        self.check_config()
        count = 0
        with self.path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    posting = RawPostingIn.model_validate(json.loads(line))
                except (ValueError, ValidationError) as exc:
                    self.errors.append(f"{self.path.name}:{n}: {exc.__class__.__name__}")
                    continue
                yield posting
                count += 1
                if ctx.limit and count >= ctx.limit:
                    return
        ctx.complete = True
