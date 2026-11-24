"""Vacancy lifecycle (FR-11, FR-26).

A vacancy is
    hidden   when it has no posting from an enabled source (e.g. the source's terms changed),
    expired  when its explicit deadline has passed, every source page has been gone for `stale_after_days`,
             or an administrator expired it (`expired_reason="admin"`, never auto-reverted),
    active   otherwise.

`expire_vacancies` is meant to run daily (Part B's scheduler). Search also filters past deadlines at query
time, so results are correct even if the job has not run yet.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import KZ_TZ, get_settings
from app.models import CanonicalVacancy, Source, SourcePosting


def kz_today(now: datetime) -> date:
    return now.astimezone(KZ_TZ).date()


def apply_status(
    vacancy: CanonicalVacancy, members: Iterable[SourcePosting], enabled_source_ids: set[int], now: datetime
) -> None:
    members = list(members)
    if vacancy.status == "expired" and vacancy.expired_reason == "admin":
        return

    usable = [m for m in members if m.source_id in enabled_source_ids]
    stale_cutoff = now - timedelta(days=get_settings().stale_after_days)

    if not usable:
        new_status, reason = "hidden", "source_disabled"
    elif vacancy.deadline is not None and vacancy.deadline < kz_today(now):
        new_status, reason = "expired", "deadline_passed"
    elif all(m.gone_since is not None and m.gone_since <= stale_cutoff for m in usable):
        new_status, reason = "expired", "source_gone"
    else:
        new_status, reason = "active", None

    if new_status != vacancy.status or reason != vacancy.expired_reason:
        vacancy.status = new_status
        vacancy.expired_reason = reason
        vacancy.expired_at = now if new_status == "expired" else None


def expire_vacancies(session: Session, now: datetime) -> int:
    """Daily job. Returns the number of vacancies whose status changed."""
    enabled = set(session.scalars(select(Source.id).where(Source.enabled.is_(True))))
    changed = 0
    vacancies = session.scalars(select(CanonicalVacancy).where(CanonicalVacancy.status.in_(("active", "expired"))))
    for vacancy in vacancies.all():
        members = session.scalars(select(SourcePosting).where(SourcePosting.canonical_vacancy_id == vacancy.id)).all()
        before = (vacancy.status, vacancy.expired_reason)
        apply_status(vacancy, members, enabled, now)
        changed += before != (vacancy.status, vacancy.expired_reason)
    session.flush()
    return changed


def set_source_enabled(session: Session, source_key: str, enabled: bool, now: datetime) -> int:
    """FR-26 / UC-05 3b: disabling a source hides vacancies that only it provided. Returns affected count."""
    source = session.scalar(select(Source).where(Source.key == source_key))
    if source is None:
        raise LookupError(source_key)
    source.enabled = enabled
    session.flush()
    vacancy_ids = set(
        session.scalars(
            select(SourcePosting.canonical_vacancy_id).where(
                SourcePosting.source_id == source.id, SourcePosting.canonical_vacancy_id.is_not(None)
            )
        )
    )
    from app.pipeline.canonical import recompute_canonical  # canonical imports this module

    for vid in vacancy_ids:
        if (vacancy := session.get(CanonicalVacancy, vid)) is not None:
            recompute_canonical(session, vacancy, now)
    return len(vacancy_ids)
