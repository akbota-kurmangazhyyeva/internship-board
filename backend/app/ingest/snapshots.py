"""Raw response store (FR-03).

Every HTTP response an adapter receives is written, unmodified, as a gzip-compressed JSON file:

    <snapshot_dir>/<source_key>/<YYYY-MM-DD>/<HHMMSS>-<seq>-<sha12>.json.gz

The pipeline already keeps each posting's text in `raw_snapshots`; this store keeps the *response* the posting came
from (list pages, detail pages, headers, status), so a run can be audited or replayed offline, and adapter fixtures
for tests can be taken from real traffic. Files are write-once; nothing here is ever edited.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Headers worth keeping for audit. Cookies and auth headers are never stored.
_KEEP_HEADERS = {"content-type", "date", "etag", "last-modified", "x-wp-total", "x-wp-totalpages", "retry-after"}


@dataclass(frozen=True)
class StoredResponse:
    path: Path
    sha256: str


class RawResponseStore:
    def __init__(self, root: Path, source_key: str) -> None:
        self.root = Path(root)
        self.source_key = source_key
        self._seq = 0

    def save(
        self,
        *,
        url: str,
        status: int,
        body: str,
        headers: dict[str, str] | None = None,
        fetched_at: datetime | None = None,
    ) -> StoredResponse:
        fetched_at = fetched_at or datetime.now(UTC)
        self._seq += 1
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        folder = self.root / self.source_key / fetched_at.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{fetched_at.strftime('%H%M%S')}-{self._seq:04d}-{sha[:12]}.json.gz"
        record = {
            "source": self.source_key,
            "url": url,
            "status": status,
            "fetched_at": fetched_at.isoformat(),
            "headers": {k.lower(): v for k, v in (headers or {}).items() if k.lower() in _KEEP_HEADERS},
            "sha256": sha,
            "body": body,
        }
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        return StoredResponse(path, sha)


def read_snapshot(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def iter_snapshots(root: Path, source_key: str, day: str | None = None) -> Iterator[dict[str, Any]]:
    """Replay stored responses in collection order, e.g. to rebuild fixtures or debug a run."""
    base = Path(root) / source_key
    folders = [base / day] if day else sorted(p for p in base.glob("*") if p.is_dir())
    for folder in folders:
        for path in sorted(folder.glob("*.json.gz")):
            yield read_snapshot(path)


class NullStore(RawResponseStore):
    """For tests and dry runs."""

    def __init__(self) -> None:
        super().__init__(Path("/dev/null"), "null")

    def save(self, **kwargs: Any) -> StoredResponse:  # type: ignore[override]
        body = kwargs.get("body", "")
        return StoredResponse(Path("/dev/null"), hashlib.sha256(body.encode()).hexdigest())
