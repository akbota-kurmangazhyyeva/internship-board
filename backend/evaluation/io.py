from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import KZ_TZ
from app.extraction import ExtractionResult, PostingText, extract
from evaluation.schema import EvalPosting, EvalProfile, GoldLabel, Judgment

M = TypeVar("M", bound=BaseModel)
BACKEND = Path(__file__).resolve().parent.parent
TEST_DIR = BACKEND / "evaluation" / "data" / "test"
DEV_DIR = BACKEND / "evaluation" / "data" / "dev"
REPORTS_DIR = BACKEND / "evaluation" / "reports"
FILES = ("postings.jsonl", "labels.jsonl", "profiles.jsonl", "judgments.jsonl")


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                yield n, json.loads(line)


def load(path: Path, model: type[M]) -> list[M]:
    if not path.exists():
        return []
    return [model.model_validate(obj) for _, obj in iter_jsonl(path)]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def is_frozen(directory: Path) -> bool:
    return (directory / "FROZEN.json").exists()


class Dataset:
    def __init__(self, directory: Path):
        self.dir = directory
        self.postings: list[EvalPosting] = [_aware(p) for p in load(directory / "postings.jsonl", EvalPosting)]
        self.labels: dict[str, GoldLabel] = {g.posting_id: g for g in load(directory / "labels.jsonl", GoldLabel)}
        self.profiles: list[EvalProfile] = load(directory / "profiles.jsonl", EvalProfile)
        self.judgments: list[Judgment] = load(directory / "judgments.jsonl", Judgment)
        if not self.postings:
            raise SystemExit(f"no postings found in {directory / 'postings.jsonl'}")

    @property
    def frozen(self) -> bool:
        return is_frozen(self.dir)

    @property
    def labelled(self) -> list[tuple[EvalPosting, GoldLabel]]:
        return [(p, self.labels[p.posting_id]) for p in self.postings if p.posting_id in self.labels]

    def reference_date(self) -> date:
        dates = [p.published_at.astimezone(KZ_TZ).date() for p in self.postings if p.published_at]
        return max(dates) if dates else date.today()


def _aware(p: EvalPosting) -> EvalPosting:
    if p.published_at is not None and p.published_at.tzinfo is None:
        p.published_at = p.published_at.replace(tzinfo=KZ_TZ)
    return p


def to_text(p: EvalPosting) -> PostingText:
    return PostingText(
        title=p.title,
        description=p.description,
        employer=p.employer,
        url=p.url,
        apply_url=p.apply_url,
        published_at=p.published_at,
        source_fields=p.source_fields,
    )


def run_extraction(p: EvalPosting) -> ExtractionResult:
    return extract(to_text(p))


def report_path(kind: str, directory: Path, suffix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR / f"{kind}-{directory.name}-{stamp}.{suffix}"
