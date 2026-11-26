"""Building the seed dataset (≥ 60 real postings) for evaluation and demos.

Two ways in, both producing JSONL with one RawPostingIn per line:

1. Automatic, from a live adapter, without touching the database:
       python -m app.cli collect-seed indrive_careers --limit 40 --out data/seed/indrive.jsonl
2. Manual, for sources we may read but not automate (Telegram channels, LinkedIn, university career centre emails):
   the team fills one row per posting in a shared sheet (columns below), exports CSV, then
       python -m app.cli seed-from-csv data/seed/manual.csv --out data/seed/manual.jsonl

   Required columns: source, url, title, description
   Optional columns: external_id, employer, published_at (YYYY-MM-DD or ISO), apply_url, collected_by, notes

`merge_seed` concatenates the files, drops exact duplicates (same source + external id) and reports counts per
source, which goes straight into the report's dataset table.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.ingest.contract import RawPostingIn

REQUIRED = ("source", "url", "title", "description")


def _parse_date(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def row_to_posting(row: dict[str, str]) -> RawPostingIn:
    missing = [c for c in REQUIRED if not (row.get(c) or "").strip()]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    url = row["url"].strip()
    external_id = (row.get("external_id") or "").strip() or hashlib.sha1(url.encode()).hexdigest()[:16]
    return RawPostingIn(
        external_id=f"{row['source'].strip()}:{external_id}",
        url=url,
        title=row["title"].strip(),
        description=row["description"].strip(),
        employer=(row.get("employer") or "").strip() or None,
        published_at=_parse_date(row.get("published_at", "")),
        apply_url=(row.get("apply_url") or "").strip() or None,
        payload={
            "collected_from": row["source"].strip(),
            "collected_by": (row.get("collected_by") or "").strip() or None,
            "notes": (row.get("notes") or "").strip() or None,
            "collected_at": datetime.now(UTC).isoformat(),
        },
    )


def csv_to_postings(path: Path) -> tuple[list[RawPostingIn], list[str]]:
    postings, errors = [], []
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), 2):  # line 1 is the header
            try:
                postings.append(row_to_posting({k.strip().lower(): v for k, v in row.items() if k}))
            except ValueError as exc:
                errors.append(f"{path.name}:{n}: {exc}")
    return postings, errors


def write_jsonl(postings: Iterable[RawPostingIn], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as fh:
        for p in postings:
            fh.write(p.model_dump_json(exclude_none=True) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[RawPostingIn]:
    with Path(path).open(encoding="utf-8") as fh:
        return [RawPostingIn.model_validate(json.loads(line)) for line in fh if line.strip()]


def merge_seed(paths: list[Path], out: Path) -> Counter[str]:
    seen: set[str] = set()
    merged: list[RawPostingIn] = []
    per_source: Counter[str] = Counter()
    for path in paths:
        for p in read_jsonl(path):
            if p.external_id in seen:
                continue
            seen.add(p.external_id)
            merged.append(p)
            per_source[(p.payload or {}).get("collected_from") or path.stem] += 1
    write_jsonl(merged, out)
    return per_source
