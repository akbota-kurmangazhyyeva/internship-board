"""Explainable fit ranking (FR-19, FR-20; UC-01).

Step 1, hard constraints. A vacancy is ineligible if a *known* field contradicts the profile:
    level not in the student's target levels; work format not accepted; located only in other cities (and not
    remote, and the student won't relocate); explicitly for other years of study.
    Unknown fields never exclude a vacancy: we don't punish postings for what the extractor couldn't read.

Step 2, weighted overlap. Score = 100 * sum(weight * component), each component in [0, 1].
    The weights are deliberately simple and visible (WEIGHTS) so students can be told why a card ranks where it does.

Step 3, reasons. Each component that helped (or hurt) produces a Reason with a stable `code` and `params`, so
    the web app can localise them; `text` is an English fallback. `summary` is FR-20's
    "4 of 6 skills match · Almaty · Remote".

If nothing passes the hard constraints, `rank()` returns the nearest matches with relaxed=True (UC-01 5a).
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.config import KZ_TZ

# Initial, hand-set weights. Tune them on the DEV split with evaluation/eval_ranking.py, never on the frozen test set.
WEIGHTS: dict[str, float] = {
    "skills": 0.40,
    "interests": 0.15,
    "location": 0.15,
    "work_format": 0.10,
    "eligibility": 0.10,
    "language": 0.05,
    "freshness": 0.05,
}
FORMAT_LABELS = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}
LANGUAGE_LABELS = {"en": "English", "kk": "Kazakh", "ru": "Russian"}
LEVEL_LABELS = {"intern": "Internship", "junior": "Junior", "mid": "Mid-level", "senior": "Senior"}


@dataclass
class Profile:
    skills: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    field_of_study: str | None = None
    preferred_cities: list[str] = field(default_factory=list)
    work_formats: list[str] = field(default_factory=list)  # acceptable; empty = any
    target_levels: list[str] = field(default_factory=lambda: ["intern", "junior"])
    languages: list[str] = field(default_factory=list)
    year_of_study: int | None = None
    open_to_relocation: bool = False

    @property
    def completeness(self) -> float:
        parts = [self.skills, self.interests or self.field_of_study, self.preferred_cities, self.year_of_study]
        return sum(1 for p in parts if p) / len(parts)


@dataclass
class VacancyView:
    id: Hashable
    title: str
    description: str = ""
    skills: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    work_format: str | None = None
    level: str | None = None
    languages: list[str] = field(default_factory=list)
    eligibility: dict[str, Any] | None = None
    deadline: date | None = None
    published_at: datetime | None = None


@dataclass
class Reason:
    code: str
    text: str
    polarity: int  # +1 helps, -1 hurts, 0 informative
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class FitResult:
    vacancy_id: Hashable
    score: float
    eligible: bool
    reasons: list[Reason]
    violations: list[Reason]
    components: dict[str, float]

    @property
    def summary(self) -> str:
        return " · ".join([r.text for r in self.reasons if r.polarity > 0][:3])


@dataclass
class Ranked:
    items: list[FitResult]
    relaxed: bool


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _years_text(min_year: int | None, max_year: int | None) -> str:
    if min_year and max_year:
        return (
            f"{_ordinal(min_year)}-year students"
            if min_year == max_year
            else f"{_ordinal(min_year)}–{_ordinal(max_year)}-year students"
        )
    if min_year:
        return f"{_ordinal(min_year)}-year students and above"
    return f"students up to {_ordinal(max_year)} year" if max_year else "students"


def _terms(profile: Profile) -> list[str]:
    terms = [t.strip() for t in profile.interests if t.strip()]
    if profile.field_of_study:
        terms += [t.strip() for t in re.split(r"[,;/]", profile.field_of_study) if t.strip()]
    return terms


def score(profile: Profile, v: VacancyView, today: date | None = None) -> FitResult:
    today = today or datetime.now(KZ_TZ).date()
    reasons: list[Reason] = []
    violations: list[Reason] = []
    comp: dict[str, float] = {}

    # ---- hard constraints
    if v.level and profile.target_levels and v.level not in profile.target_levels:
        violations.append(
            Reason("level_mismatch", f"{LEVEL_LABELS.get(v.level, v.level)} position", -1, {"level": v.level})
        )
    if v.work_format and profile.work_formats and v.work_format not in profile.work_formats:
        violations.append(
            Reason("format_mismatch", f"{FORMAT_LABELS[v.work_format]} only", -1, {"work_format": v.work_format})
        )
    other_city = (
        v.cities
        and v.work_format != "remote"
        and profile.preferred_cities
        and not set(v.cities) & set(profile.preferred_cities)
    )
    if other_city and not profile.open_to_relocation:
        violations.append(Reason("location_mismatch", f"Located in {', '.join(v.cities)}", -1, {"cities": v.cities}))
    elig = v.eligibility or {}
    lo, hi = elig.get("min_year"), elig.get("max_year")
    year = profile.year_of_study
    if year and ((lo and year < lo) or (hi and year > hi)):
        violations.append(Reason("year_mismatch", f"For {_years_text(lo, hi)}", -1, {"min_year": lo, "max_year": hi}))

    # ---- skills
    if v.skills and profile.skills:
        mine = {s.lower() for s in profile.skills}
        matched = [s for s in v.skills if s.lower() in mine]
        # Coverage of the vacancy's requirements, plus credit for the absolute number of matches
        # (4 of 6 is stronger evidence than 1 of 2).
        comp["skills"] = 0.6 * len(matched) / len(v.skills) + 0.4 * min(1.0, len(matched) / 3)
        if matched:
            reasons.append(
                Reason(
                    "skills_match",
                    f"{len(matched)} of {len(v.skills)} skills match",
                    1,
                    {"matched": matched, "total": len(v.skills)},
                )
            )
        else:
            reasons.append(
                Reason("skills_none", "None of the listed skills match your profile", -1, {"total": len(v.skills)})
            )
    else:
        comp["skills"] = 0.5

    # ---- interests / field of study
    terms = _terms(profile)
    if terms:
        title, body = v.title.lower(), (v.description or "").lower()
        skills_lower = {s.lower() for s in v.skills}
        hits: list[str] = []
        value = 0.0
        for t in terms:
            tl = t.lower()
            if tl in title or tl in skills_lower:
                value += 1.0
                hits.append(t)
            elif tl in body:
                value += 0.5
                hits.append(t)
        comp["interests"] = max(0.2, min(1.0, value))  # substring matching is incomplete: a miss is weak evidence
        if hits:
            reasons.append(Reason("interest_match", f"Matches your interest: {hits[0]}", 1, {"interests": hits}))
    else:
        comp["interests"] = 0.5

    # ---- location
    if v.work_format == "remote":
        comp["location"] = 1.0
    elif v.cities and profile.preferred_cities:
        shared = [c for c in v.cities if c in profile.preferred_cities]
        if shared:
            comp["location"] = 1.0
            reasons.append(Reason("city_match", shared[0], 1, {"city": shared[0]}))
        else:
            comp["location"] = 0.3
            reasons.append(Reason("relocation", f"Requires relocation to {v.cities[0]}", -1, {"city": v.cities[0]}))
    elif v.cities:
        comp["location"] = 0.7
        reasons.append(Reason("city", v.cities[0], 0, {"city": v.cities[0]}))
    else:
        comp["location"] = 0.5

    # ---- work format
    if v.work_format:
        accepted = not profile.work_formats or v.work_format in profile.work_formats
        comp["work_format"] = 1.0 if accepted else 0.0
        reasons.append(
            Reason("work_format", FORMAT_LABELS[v.work_format], 1 if accepted else -1, {"work_format": v.work_format})
        )
    else:
        comp["work_format"] = 0.5

    # ---- eligibility
    if profile.year_of_study and (lo or hi):
        ok = not ((lo and profile.year_of_study < lo) or (hi and profile.year_of_study > hi))
        comp["eligibility"] = 1.0 if ok else 0.0
        if ok:
            reasons.append(Reason("year_match", f"Open to {_years_text(lo, hi)}", 1, {"min_year": lo, "max_year": hi}))
    else:
        comp["eligibility"] = 0.5

    # ---- language requirements
    if v.languages and profile.languages:
        missing = [lang for lang in v.languages if lang not in profile.languages]
        comp["language"] = 0.0 if missing else 1.0
        for lang in missing:
            reasons.append(
                Reason("language_missing", f"Requires {LANGUAGE_LABELS.get(lang, lang)}", -1, {"language": lang})
            )
    else:
        comp["language"] = 1.0 if not v.languages else 0.7

    # ---- freshness (30-day e-folding) and informative deadline note
    if v.published_at:
        age_days = max(0.0, (datetime.now(v.published_at.tzinfo) - v.published_at).total_seconds() / 86400)
        comp["freshness"] = math.exp(-age_days / 30)
    else:
        comp["freshness"] = 0.5
    if v.deadline:
        days_left = (v.deadline - today).days
        if 0 <= days_left <= 7:
            reasons.append(
                Reason(
                    "deadline_soon",
                    f"Deadline in {days_left} day{'s' if days_left != 1 else ''}",
                    0,
                    {"days": days_left},
                )
            )

    total = 100 * sum(WEIGHTS[k] * comp[k] for k in WEIGHTS)
    reasons.sort(key=lambda r: -r.polarity)
    return FitResult(
        v.id, round(total, 1), not violations, reasons, violations, {k: round(c, 3) for k, c in comp.items()}
    )


def rank(
    profile: Profile, vacancies: Sequence[VacancyView], today: date | None = None, *, relax_if_empty: bool = True
) -> Ranked:
    results = [(score(profile, v, today), v) for v in vacancies]

    def order(item: tuple[FitResult, VacancyView]) -> tuple:
        fit, v = item
        return (-fit.score, v.deadline or date.max, -(v.published_at.timestamp() if v.published_at else 0))

    eligible = sorted((r for r in results if r[0].eligible), key=order)
    if eligible or not relax_if_empty:
        return Ranked([fit for fit, _ in eligible], relaxed=False)
    return Ranked([fit for fit, _ in sorted(results, key=order)], relaxed=True)
