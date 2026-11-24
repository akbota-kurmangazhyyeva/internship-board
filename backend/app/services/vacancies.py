"""Search, filters, ranked feed and detail (FR-16..FR-22, UC-01, UC-02)."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import ColumnElement, Select, and_, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.config import KZ_TZ
from app.models import CanonicalVacancy, Interaction, SavedVacancy, Source, SourcePosting, StudentProfile, User
from app.ranking import FitResult, Profile, VacancyView, rank, score
from app.schemas import (
    FeedPage,
    FieldMetaOut,
    FitOut,
    ReasonOut,
    SourceLinkOut,
    VacancyCard,
    VacancyDetail,
)

FIT_CANDIDATE_CAP = 2000  # pilot scale; beyond this, pre-filter in SQL or move scoring into the database


@dataclass
class VacancyFilters:
    q: str | None = None
    skills: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    work_formats: list[str] = field(default_factory=list)
    levels: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    deadline_from: date | None = None
    deadline_to: date | None = None
    internship_only: bool = False


def kz_today() -> date:
    return datetime.now(KZ_TZ).date()


# --------------------------------------------------------------------------- query building


def ts_query(q: str) -> ColumnElement | None:
    """Russian + English stemmed web-search queries OR'd with an unstemmed prefix query (covers Kazakh suffixes)."""
    q = q.strip()
    if not q:
        return None
    parts: list[ColumnElement] = [
        func.websearch_to_tsquery(literal_column("'russian'::regconfig"), q),
        func.websearch_to_tsquery(literal_column("'english'::regconfig"), q),
    ]
    tokens = [t for t in re.findall(r"\w+", q.lower()) if len(t) >= 3]
    if tokens:
        parts.append(func.to_tsquery(literal_column("'simple'::regconfig"), " & ".join(f"{t}:*" for t in tokens)))
    combined = parts[0]
    for part in parts[1:]:
        combined = combined.op("||")(part)
    return combined


def active_clause(today: date) -> ColumnElement[bool]:
    return and_(
        CanonicalVacancy.status == "active",
        or_(CanonicalVacancy.deadline.is_(None), CanonicalVacancy.deadline >= today),
    )


def filtered(f: VacancyFilters, today: date) -> tuple[Select, ColumnElement | None]:
    stmt = select(CanonicalVacancy).where(active_clause(today))
    tsq = ts_query(f.q) if f.q else None
    if tsq is not None:
        stmt = stmt.where(CanonicalVacancy.search_vector.op("@@")(tsq))
    if f.skills:
        stmt = stmt.where(CanonicalVacancy.skills.overlap(f.skills))
    if f.cities:
        stmt = stmt.where(CanonicalVacancy.cities.overlap(f.cities))
    if f.languages:
        stmt = stmt.where(CanonicalVacancy.languages.overlap(f.languages))
    if f.work_formats:
        stmt = stmt.where(CanonicalVacancy.work_format.in_(f.work_formats))
    if f.levels:
        stmt = stmt.where(CanonicalVacancy.level.in_(f.levels))
    if f.internship_only:
        stmt = stmt.where(CanonicalVacancy.is_internship.is_(True))
    if f.deadline_from:
        stmt = stmt.where(CanonicalVacancy.deadline >= f.deadline_from)
    if f.deadline_to:
        stmt = stmt.where(CanonicalVacancy.deadline <= f.deadline_to)
    return stmt, tsq


def _order(stmt: Select, sort: str, tsq: ColumnElement | None) -> Select:
    V = CanonicalVacancy
    if sort == "relevance" and tsq is not None:
        return stmt.order_by(
            func.ts_rank_cd(V.search_vector, tsq).desc(), V.published_at.desc().nulls_last(), V.id.desc()
        )
    if sort == "deadline":
        return stmt.order_by(V.deadline.asc().nulls_last(), V.published_at.desc().nulls_last(), V.id.desc())
    return stmt.order_by(V.published_at.desc().nulls_last(), V.id.desc())


# --------------------------------------------------------------------------- conversion helpers


def to_profile(p: StudentProfile | None) -> Profile:
    if p is None:
        return Profile()
    return Profile(
        skills=list(p.skills),
        interests=list(p.interests),
        field_of_study=p.field_of_study,
        preferred_cities=list(p.preferred_cities),
        work_formats=list(p.work_formats),
        target_levels=list(p.target_levels),
        languages=list(p.languages),
        year_of_study=p.year_of_study,
        open_to_relocation=p.open_to_relocation,
    )


def to_view(v: CanonicalVacancy) -> VacancyView:
    return VacancyView(
        id=v.id,
        title=v.title,
        description=v.description,
        skills=list(v.skills),
        cities=list(v.cities),
        work_format=v.work_format,
        level=v.level,
        languages=list(v.languages),
        eligibility=v.eligibility,
        deadline=v.deadline,
        published_at=v.published_at,
    )


def fit_out(fit: FitResult) -> FitOut:
    def conv(rs):
        return [ReasonOut(code=r.code, text=r.text, polarity=r.polarity, params=r.params) for r in rs]

    return FitOut(
        score=fit.score,
        eligible=fit.eligible,
        summary=fit.summary,
        reasons=conv(fit.reasons),
        violations=conv(fit.violations),
    )


def _source_names(session: Session, ids: Sequence[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    rows = session.execute(
        select(SourcePosting.canonical_vacancy_id, Source.name)
        .join(Source, Source.id == SourcePosting.source_id)
        .where(SourcePosting.canonical_vacancy_id.in_(ids), Source.enabled.is_(True))
        .distinct()
    )
    out: dict[int, list[str]] = defaultdict(list)
    for vid, name in rows:
        out[vid].append(name)
    return {k: sorted(v) for k, v in out.items()}


def _saved_ids(session: Session, user: User | None, ids: Sequence[int]) -> set[int] | None:
    if user is None:
        return None
    if not ids:
        return set()
    return set(
        session.scalars(
            select(SavedVacancy.vacancy_id).where(SavedVacancy.user_id == user.id, SavedVacancy.vacancy_id.in_(ids))
        )
    )


def _card_fields(v: CanonicalVacancy, sources: list[str]) -> dict:
    return dict(
        id=v.id,
        title=v.title,
        employer=v.employer_name,
        status=v.status,
        is_internship=v.is_internship,
        level=v.level,
        work_format=v.work_format,
        cities=list(v.cities),
        skills=list(v.skills),
        languages=list(v.languages),
        deadline=v.deadline,
        salary=v.salary,
        published_at=v.published_at,
        last_checked_at=v.last_checked_at,
        sources=sources,
    )


def build_cards(
    session: Session,
    vacancies: Sequence[CanonicalVacancy],
    user: User | None,
    fits: dict[int, FitResult] | None = None,
) -> list[VacancyCard]:
    ids = [v.id for v in vacancies]
    names = _source_names(session, ids)
    saved = _saved_ids(session, user, ids)
    if fits is None and user is not None and user.profile is not None:
        profile, today = to_profile(user.profile), kz_today()
        fits = {v.id: score(profile, to_view(v), today) for v in vacancies}
    return [
        VacancyCard(
            **_card_fields(v, names.get(v.id, [])),
            fit=fit_out(fits[v.id]) if fits and v.id in fits else None,
            is_saved=None if saved is None else v.id in saved,
        )
        for v in vacancies
    ]


# --------------------------------------------------------------------------- public operations


def search(
    session: Session, f: VacancyFilters, sort: str, limit: int, offset: int, user: User | None
) -> tuple[list[VacancyCard], int]:
    today = kz_today()
    stmt, tsq = filtered(f, today)
    if sort == "fit" and user is not None and user.profile is not None:
        # Unlike /feed, sort=fit hides nothing: ineligible vacancies just sink to the bottom.
        vacancies = session.scalars(stmt.limit(FIT_CANDIDATE_CAP)).all()
        profile = to_profile(user.profile)
        fits = {v.id: score(profile, to_view(v), today) for v in vacancies}
        ordered = sorted(vacancies, key=lambda v: (not fits[v.id].eligible, -fits[v.id].score, -v.id))
        return build_cards(session, ordered[offset : offset + limit], user, fits), len(vacancies)

    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = session.scalars(_order(stmt, "newest" if sort == "fit" else sort, tsq).limit(limit).offset(offset)).all()
    return build_cards(session, page, user), total


def feed(session: Session, user: User, f: VacancyFilters, limit: int, offset: int) -> FeedPage:
    """Personalised ranked feed: hard constraints, then fit; dismissed vacancies removed (FR-19..21)."""
    today = kz_today()
    stmt, _ = filtered(f, today)
    hidden = select(Interaction.vacancy_id).where(
        Interaction.user_id == user.id, Interaction.kind.in_(("dismiss", "not_relevant"))
    )
    stmt = stmt.where(CanonicalVacancy.id.not_in(hidden))
    vacancies = session.scalars(stmt.limit(FIT_CANDIDATE_CAP)).all()

    profile = to_profile(user.profile)
    ranked = rank(profile, [to_view(v) for v in vacancies], today)
    by_id = {v.id: v for v in vacancies}
    fits = {r.vacancy_id: r for r in ranked.items}
    page = [by_id[r.vacancy_id] for r in ranked.items[offset : offset + limit]]

    complete = profile.completeness >= 0.75
    hint = None
    if user.profile is None:
        hint = "Create your profile to get a personalised feed."
    elif not complete:
        hint = "Complete your profile (skills, interests, cities, year of study) for better matches."
    if ranked.relaxed and ranked.items:
        hint = (
            "Nothing matches all your preferences yet. Showing the nearest matches; try relaxing city, format or level."
        )
    return FeedPage(
        items=build_cards(session, page, user, fits),
        total=len(ranked.items),
        limit=limit,
        offset=offset,
        relaxed=ranked.relaxed,
        profile_complete=complete,
        hint=hint,
    )


def get_detail(session: Session, vacancy_id: int, user: User | None) -> VacancyDetail | None:
    v = session.get(CanonicalVacancy, vacancy_id)
    if v is None or v.status == "hidden":
        return None
    card = build_cards(session, [v], user)[0]
    rows = session.execute(
        select(SourcePosting, Source)
        .join(Source, Source.id == SourcePosting.source_id)
        .where(SourcePosting.canonical_vacancy_id == v.id, Source.enabled.is_(True))
        .order_by(SourcePosting.first_seen_at)
    ).all()
    links = [
        SourceLinkOut(
            source=src.name,
            source_key=src.key,
            url=sp.url,
            first_seen_at=sp.first_seen_at,
            last_checked_at=sp.last_checked_at,
            live=sp.gone_since is None,
        )
        for sp, src in rows
    ]
    fields = {
        name: FieldMetaOut(
            status=m.get("status", "missing"),
            confidence=m.get("confidence"),
            method=m.get("method"),
            evidence=m.get("evidence"),
        )
        for name, m in (v.field_meta or {}).items()
    }
    return VacancyDetail(
        **card.model_dump(),
        description=v.description,
        posting_language=v.posting_language,
        eligibility=v.eligibility,
        apply_url=v.apply_url,
        fields=fields,
        source_links=links,
    )
