"""Request and response models of the public API (the contract for the web app)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.extraction.vocab import normalize_city, normalize_skill

Level = Literal["intern", "junior", "mid", "senior"]
WorkFormat = Literal["remote", "hybrid", "onsite"]
Language = Literal["kk", "ru", "en"]
EducationLevel = Literal["college", "bachelor", "master", "phd"]
Sort = Literal["relevance", "newest", "deadline", "fit"]

T = TypeVar("T")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for v in values:
        if v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


# --------------------------------------------------------------------------- auth & account


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    tracking_consent: bool


class ConsentIn(BaseModel):
    tracking: bool


# --------------------------------------------------------------------------- profile (FR-14, DR-08)


class ProfileIn(BaseModel):
    education_level: EducationLevel | None = None
    year_of_study: int | None = Field(default=None, ge=1, le=6)
    expected_graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    field_of_study: str | None = Field(default=None, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=50)
    preferred_cities: list[str] = Field(default_factory=list, max_length=25)
    work_formats: list[WorkFormat] = Field(default_factory=list, description="Acceptable formats; empty = any")
    target_levels: list[Level] = Field(default_factory=lambda: ["intern", "junior"])
    languages: list[Language] = Field(default_factory=list, description="Languages the student can work in")
    interests: list[str] = Field(default_factory=list, max_length=20)
    open_to_relocation: bool = False

    @field_validator("skills")
    @classmethod
    def _canonical_skills(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip()[:60] for s in v if s.strip()]
        return _dedupe([normalize_skill(s) or s for s in cleaned])

    @field_validator("preferred_cities")
    @classmethod
    def _canonical_cities(cls, v: list[str]) -> list[str]:
        out = []
        for raw in v:
            name = normalize_city(raw)
            if name is None:
                raise ValueError(f"unknown city {raw!r}; see GET /api/v1/meta/filters for the list")
            out.append(name)
        return _dedupe(out)

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, v: list[str]) -> list[str]:
        return _dedupe([s.strip()[:80] for s in v if s.strip()])


class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = None


# --------------------------------------------------------------------------- vacancies


class ReasonOut(BaseModel):
    code: str
    text: str
    polarity: int
    params: dict[str, Any] = Field(default_factory=dict)


class FitOut(BaseModel):
    score: float = Field(description="0–100")
    eligible: bool = Field(description="False if a hard constraint (level, format, city, year) is violated")
    summary: str = Field(description='e.g. "4 of 6 skills match · Almaty · Remote"')
    reasons: list[ReasonOut]
    violations: list[ReasonOut]


class VacancyCard(BaseModel):
    id: int
    title: str
    employer: str | None
    status: str
    is_internship: bool | None
    level: Level | None = Field(description="null = Unknown (not stated or low confidence)")
    work_format: WorkFormat | None
    cities: list[str]
    skills: list[str]
    languages: list[str]
    deadline: date | None
    salary: dict[str, Any] | None
    published_at: datetime | None
    last_checked_at: datetime
    sources: list[str]
    fit: FitOut | None = None
    is_saved: bool | None = None


class FieldMetaOut(BaseModel):
    status: str = Field(description="ok | low_confidence | conflict | missing")
    confidence: float | None = None
    method: str | None = None
    evidence: str | None = None


class SourceLinkOut(BaseModel):
    source: str
    source_key: str
    url: str
    first_seen_at: datetime
    last_checked_at: datetime
    live: bool


class VacancyDetail(VacancyCard):
    description: str
    posting_language: str | None
    eligibility: dict[str, Any] | None
    apply_url: str | None
    fields: dict[str, FieldMetaOut]
    source_links: list[SourceLinkOut]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class FeedPage(Page[VacancyCard]):
    relaxed: bool = Field(description="True if nothing met the hard constraints and nearest matches are shown")
    profile_complete: bool
    hint: str | None = None


class SaveIn(BaseModel):
    remind: bool = True


class SavedOut(BaseModel):
    vacancy: VacancyCard
    saved_at: datetime
    remind: bool


class InteractionIn(BaseModel):
    vacancy_id: int
    kind: Literal["view", "click_apply", "dismiss", "not_relevant"]


class InteractionOut(BaseModel):
    recorded: bool
    reason: str | None = None


class FiltersMeta(BaseModel):
    cities: list[str]
    skills: list[str]
    levels: list[str]
    work_formats: list[str]
    languages: list[str]
    sorts: list[str]
