"""Vacancy list / search / filter / detail and the personalised feed (FR-16..FR-20, UC-01, UC-02)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, OptionalUser, SessionDep
from app.extraction.vocab import normalize_city, normalize_skill
from app.schemas import FeedPage, Language, Level, Page, Sort, VacancyCard, VacancyDetail, WorkFormat
from app.services import vacancies as svc

router = APIRouter(tags=["vacancies"])


def _filters(
    q: Annotated[str | None, Query(max_length=200, description="Keywords in Kazakh, Russian or English")] = None,
    skill: Annotated[list[str] | None, Query(description="Repeatable; matches any")] = None,
    city: Annotated[list[str] | None, Query(description="Canonical city names; matches any")] = None,
    work_format: Annotated[list[WorkFormat] | None, Query()] = None,
    level: Annotated[list[Level] | None, Query()] = None,
    language: Annotated[list[Language] | None, Query(description="Required language")] = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    internship_only: bool = False,
) -> svc.VacancyFilters:
    return svc.VacancyFilters(
        q=q,
        skills=[normalize_skill(x) or x for x in skill or []],
        cities=[normalize_city(x) or x for x in city or []],
        work_formats=list(work_format or []),
        levels=list(level or []),
        languages=list(language or []),
        deadline_from=deadline_from,
        deadline_to=deadline_to,
        internship_only=internship_only,
    )


FiltersDep = Annotated[svc.VacancyFilters, Depends(_filters)]


@router.get("/vacancies", response_model=Page[VacancyCard])
def list_vacancies(
    session: SessionDep,
    user: OptionalUser,
    filters: FiltersDep,
    sort: Sort | None = Query(
        None, description="Default: relevance with q, fit when logged in with a profile, else newest"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[VacancyCard]:
    if sort is None:
        sort = "relevance" if filters.q else ("fit" if user is not None and user.profile is not None else "newest")
    if sort == "fit" and (user is None or user.profile is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "sort=fit needs a logged-in user with a profile")
    items, total = svc.search(session, filters, sort, limit, offset, user)
    return Page[VacancyCard](items=items, total=total, limit=limit, offset=offset)


@router.get("/vacancies/{vacancy_id}", response_model=VacancyDetail)
def vacancy_detail(vacancy_id: int, session: SessionDep, user: OptionalUser) -> VacancyDetail:
    detail = svc.get_detail(session, vacancy_id, user)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vacancy not found")
    return detail


@router.get("/feed", response_model=FeedPage)
def personal_feed(
    session: SessionDep,
    user: CurrentUser,
    filters: FiltersDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> FeedPage:
    return svc.feed(session, user, filters, limit, offset)
