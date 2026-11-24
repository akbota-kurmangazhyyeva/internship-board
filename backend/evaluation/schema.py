"""Gold-label formats. See evaluation/README.md for the labelling guidelines.

A dataset directory contains:
    postings.jsonl   one RawPostingIn per line, plus "posting_id" (and optionally "source")
    labels.jsonl     one GoldLabel per posting
    profiles.jsonl   ranking personas (optional): {"profile_id": "p1", ...profile fields}
    judgments.jsonl  relevance judgments (optional): {"profile_id": "p1", "posting_id": "t07", "grade": 0-3}
    FROZEN.json      test split only: SHA-256 of the files above, written by `python -m evaluation.freeze`
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.extraction.vocab import normalize_city, normalize_skill
from app.ingest.contract import RawPostingIn
from app.schemas import ProfileIn

Level = Literal["intern", "junior", "mid", "senior"]
WorkFormat = Literal["remote", "hybrid", "onsite"]
Lang = Literal["kk", "ru", "en"]


class EvalPosting(RawPostingIn):
    posting_id: str
    source: str = "unknown"


class SalaryGold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    currency: Literal["KZT", "USD", "RUB", "EUR"] | None = None
    unpaid: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> SalaryGold:
        if self.unpaid and (self.min is not None or self.max is not None):
            raise ValueError("an unpaid salary has no amounts")
        if not self.unpaid and self.min is None and self.max is None:
            raise ValueError("salary needs min and/or max, or unpaid=true; use null if no salary is stated")
        return self


class EligibilityGold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_year: int | None = Field(default=None, ge=1, le=6)
    max_year: int | None = Field(default=None, ge=1, le=6)


class GoldLabel(BaseModel):
    """What the posting *states*. Labellers must not look at extractor output (blind labelling)."""

    model_config = ConfigDict(extra="forbid")

    posting_id: str
    posting_language: Literal["kk", "ru", "en", "mixed"]
    is_internship: bool
    level: Level | None
    skills: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    work_format: WorkFormat | None
    deadline: date | None
    salary: SalaryGold | None
    languages: list[Lang] = Field(default_factory=list)
    eligibility: EligibilityGold | None
    apply_url: str | None
    duplicate_group: str | None = Field(default=None, description="Same value = same internship (reposts)")
    labeler: str = Field(min_length=1)
    notes: str = ""

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        return sorted({normalize_skill(s) or s.strip() for s in v if s.strip()}, key=str.lower)

    @field_validator("cities")
    @classmethod
    def _cities(cls, v: list[str]) -> list[str]:
        out = set()
        for c in v:
            name = normalize_city(c)
            if name is None:
                raise ValueError(f"unknown city {c!r} (add it to app/extraction/vocab.py first)")
            out.add(name)
        return sorted(out)


class EvalProfile(ProfileIn):
    profile_id: str
    description: str = ""


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    posting_id: str
    grade: int = Field(ge=0, le=3, description="0 not relevant, 1 marginal, 2 relevant, 3 perfect fit")
    judge: str = ""
