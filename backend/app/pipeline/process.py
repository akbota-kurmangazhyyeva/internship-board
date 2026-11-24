"""Processing pipeline: snapshot -> extraction -> duplicate grouping -> canonical vacancy (UC-04, FR-03..FR-09).

Adapters call `ingest_posting` (or `ingest_batch`). The caller owns the transaction for `ingest_posting`;
`ingest_batch` commits after each posting so one bad record cannot sink a whole run.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dedup import DedupRecord, Features, assign, employer_key
from app.extraction import EXTRACTOR_VERSION, ExtractionResult, PostingText, extract
from app.extraction.extractor import REVIEWABLE_FIELDS
from app.extraction.normalize import normalize_text
from app.extraction.types import CONFLICT, LOW
from app.ingest.contract import RawPostingIn
from app.models import CanonicalVacancy, ExtractedField, RawSnapshot, ReviewItem, Source, SourcePosting
from app.pipeline.canonical import public_values, recompute_canonical, snapshot_fields

log = logging.getLogger(__name__)


class UnknownSourceError(LookupError):
    pass


class SourceDisabledError(RuntimeError):
    pass


@dataclass
class IngestResult:
    status: str  # new | changed | unchanged | error
    external_id: str
    source_posting_id: int | None = None
    canonical_vacancy_id: int | None = None
    error: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_source(
    session: Session, key: str, *, name: str | None = None, kind: str = "file", base_url: str | None = None
) -> Source:
    source = session.scalar(select(Source).where(Source.key == key))
    if source is None:
        source = Source(key=key, name=name or key, kind=kind, base_url=base_url)
        session.add(source)
        session.flush()
    return source


def latest_snapshot(session: Session, sp: SourcePosting) -> RawSnapshot | None:
    return session.scalar(
        select(RawSnapshot).where(RawSnapshot.source_posting_id == sp.id, RawSnapshot.content_hash == sp.content_hash)
    )


def posting_text(snap: RawSnapshot, url: str | None) -> PostingText:
    return PostingText(
        title=snap.title,
        description=snap.description,
        employer=snap.employer,
        url=url,
        apply_url=snap.apply_url,
        published_at=snap.published_at,
        collected_at=snap.collected_at,
        source_fields=snap.source_fields or {},
    )


# --------------------------------------------------------------------------- ingestion


def ingest_posting(
    session: Session, source_key: str, posting: RawPostingIn, *, now: datetime | None = None
) -> IngestResult:
    now = now or utcnow()
    source = session.scalar(select(Source).where(Source.key == source_key))
    if source is None:
        raise UnknownSourceError(f"source {source_key!r} is not registered")
    if not source.enabled:
        raise SourceDisabledError(f"source {source_key!r} is disabled")

    sp = session.scalar(
        select(SourcePosting).where(
            SourcePosting.source_id == source.id, SourcePosting.external_id == posting.external_id
        )
    )
    content_hash = posting.content_hash()
    if sp is None:
        sp = SourcePosting(
            source_id=source.id,
            external_id=posting.external_id,
            url=posting.url,
            first_seen_at=now,
            last_seen_at=now,
            last_checked_at=now,
        )
        session.add(sp)
        status = "new"
    else:
        was_gone = sp.gone_since is not None
        sp.url = posting.url
        sp.last_seen_at = sp.last_checked_at = now
        sp.gone_since = None
        status = "unchanged" if sp.content_hash == content_hash else "changed"
        if status == "unchanged":
            if sp.canonical_vacancy_id is not None:
                vacancy = session.get(CanonicalVacancy, sp.canonical_vacancy_id)
                if vacancy is not None:
                    if was_gone:
                        recompute_canonical(session, vacancy, now)
                    else:
                        vacancy.last_checked_at = now
            session.flush()
            return IngestResult(status, posting.external_id, sp.id, sp.canonical_vacancy_id)

    session.flush()
    snap = session.scalar(
        select(RawSnapshot).where(RawSnapshot.source_posting_id == sp.id, RawSnapshot.content_hash == content_hash)
    )
    if snap is None:  # a posting can revert to an earlier version; reuse that snapshot
        snap = RawSnapshot(
            source_posting_id=sp.id,
            content_hash=content_hash,
            collected_at=now,
            title=posting.title,
            employer=posting.employer,
            description=posting.description,
            published_at=posting.published_at,
            apply_url=posting.apply_url,
            source_fields=posting.source_fields,
            payload=posting.payload,
        )
        session.add(snap)
    sp.content_hash = content_hash
    session.flush()

    process_snapshot(session, sp, snap, now=now)
    return IngestResult(status, posting.external_id, sp.id, sp.canonical_vacancy_id)


def ingest_batch(
    session: Session, source_key: str, postings: Iterable[RawPostingIn], *, now: datetime | None = None
) -> list[IngestResult]:
    results = []
    for posting in postings:
        try:
            results.append(ingest_posting(session, source_key, posting, now=now))
            session.commit()
        except (UnknownSourceError, SourceDisabledError):
            session.rollback()
            raise
        except Exception as exc:  # keep going: one malformed posting must not stop the source run
            session.rollback()
            log.exception("failed to ingest %s/%s", source_key, posting.external_id)
            results.append(IngestResult("error", posting.external_id, error=str(exc)))
    return results


def mark_missing(
    session: Session, source_key: str, seen_external_ids: Iterable[str], *, now: datetime | None = None
) -> int:
    """For adapters that do full scans: postings not seen in this run are marked gone (FR-11)."""
    now = now or utcnow()
    seen = set(seen_external_ids)
    source = session.scalar(select(Source).where(Source.key == source_key))
    if source is None:
        raise UnknownSourceError(source_key)
    postings = session.scalars(
        select(SourcePosting).where(SourcePosting.source_id == source.id, SourcePosting.gone_since.is_(None))
    ).all()
    gone = [sp for sp in postings if sp.external_id not in seen]
    touched: set[int] = set()
    for sp in gone:
        sp.gone_since = now
        if sp.canonical_vacancy_id is not None:
            touched.add(sp.canonical_vacancy_id)
    session.flush()
    for vid in touched:
        if (vacancy := session.get(CanonicalVacancy, vid)) is not None:
            recompute_canonical(session, vacancy, now)
    return len(gone)


# --------------------------------------------------------------------------- processing


def process_snapshot(session: Session, sp: SourcePosting, snap: RawSnapshot, *, now: datetime | None = None) -> None:
    now = now or utcnow()
    result = extract(posting_text(snap, sp.url))
    save_extraction(session, snap, result)
    sp.employer_key = employer_key(snap.employer)
    sp.published_at = snap.published_at
    session.flush()

    if sp.canonical_vacancy_id is None:
        _link_to_canonical(session, sp, snap, result, now)

    vacancy = session.get(CanonicalVacancy, sp.canonical_vacancy_id)
    assert vacancy is not None
    recompute_canonical(session, vacancy, now)
    _queue_field_reviews(session, sp, result)
    session.flush()


def save_extraction(session: Session, snap: RawSnapshot, result: ExtractionResult) -> None:
    session.execute(delete(ExtractedField).where(ExtractedField.snapshot_id == snap.id))
    for name, fr in result.fields.items():
        session.add(
            ExtractedField(
                snapshot_id=snap.id,
                field=name,
                value=fr.value,
                status=fr.status,
                confidence=fr.confidence,
                method=fr.method,
                evidence=fr.evidence,
                span_start=fr.span[0] if fr.span else None,
                span_end=fr.span[1] if fr.span else None,
                details=fr.details,
                extractor_version=result.version,
            )
        )
    session.flush()


def _as_date(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else value


def dedup_record(sp_id: int, snap: RawSnapshot, public: dict[str, Any], fallback_time: datetime) -> DedupRecord:
    return DedupRecord(
        id=sp_id,
        title=snap.title,
        description=normalize_text(snap.description),
        employer=snap.employer,
        published_at=snap.published_at or fallback_time,
        cities=public.get("cities") or [],
        level=public.get("level"),
        deadline=_as_date(public.get("deadline")),
        skills=public.get("skills") or [],
        apply_url=public.get("apply_url"),
    )


def _link_to_canonical(
    session: Session, sp: SourcePosting, snap: RawSnapshot, result: ExtractionResult, now: datetime
) -> None:
    settings = get_settings()
    window = timedelta(days=settings.dedup_window_days)
    pub = snap.published_at or now
    new_feats = Features.of(dedup_record(sp.id, snap, result.public_values(), now))

    q = select(SourcePosting).where(
        SourcePosting.canonical_vacancy_id.is_not(None),
        SourcePosting.id != sp.id,
        or_(SourcePosting.published_at.is_(None), SourcePosting.published_at.between(pub - window, pub + window)),
    )
    if sp.employer_key:
        q = q.where(or_(SourcePosting.employer_key == sp.employer_key, SourcePosting.employer_key.is_(None)))
    candidates = session.scalars(q.order_by(SourcePosting.published_at.desc().nulls_last()).limit(500)).all()

    group_ids = {c.canonical_vacancy_id for c in candidates}
    groups: dict[int, list[Features]] = defaultdict(list)
    if group_ids:
        members = session.scalars(select(SourcePosting).where(SourcePosting.canonical_vacancy_id.in_(group_ids))).all()
        for m in members:
            m_snap = latest_snapshot(session, m)
            if m_snap is None:
                continue
            public = public_values(snapshot_fields(session, m_snap.id))
            groups[m.canonical_vacancy_id].append(Features.of(dedup_record(m.id, m_snap, public, m.first_seen_at)))

    decision = assign(
        new_feats,
        groups,
        merge_threshold=settings.dedup_merge_threshold,
        review_threshold=settings.dedup_review_threshold,
        window_days=settings.dedup_window_days,
    )
    if decision.group_id is not None:
        sp.canonical_vacancy_id = decision.group_id
        sp.match_method, sp.match_score = "auto", decision.score
    else:
        vacancy = CanonicalVacancy(title=snap.title, description="", first_seen_at=now, last_checked_at=now)
        session.add(vacancy)
        session.flush()
        sp.canonical_vacancy_id = vacancy.id
        sp.match_method, sp.match_score = "new", None
    session.flush()

    for gid, score in decision.suspected:
        if gid == sp.canonical_vacancy_id:
            continue
        session.add(
            ReviewItem(
                kind="suspected_duplicate",
                vacancy_id=sp.canonical_vacancy_id,
                source_posting_id=sp.id,
                other_vacancy_id=gid,
                details={
                    "score": score,
                    "thresholds": [settings.dedup_review_threshold, settings.dedup_merge_threshold],
                },
            )
        )


def _queue_field_reviews(session: Session, sp: SourcePosting, result: ExtractionResult) -> None:
    open_items = {
        item.field: item
        for item in session.scalars(
            select(ReviewItem).where(
                ReviewItem.source_posting_id == sp.id,
                ReviewItem.kind.in_(("low_confidence_field", "field_conflict")),
                ReviewItem.status == "open",
            )
        )
    }
    for name in REVIEWABLE_FIELDS:
        fr = result.fields[name]
        existing = open_items.get(name)
        if fr.status in (LOW, CONFLICT):
            details = {
                "value": fr.value,
                "confidence": fr.confidence,
                "method": fr.method,
                "evidence": fr.evidence,
                "extractor_version": EXTRACTOR_VERSION,
                **({"candidates": fr.details["candidates"]} if "candidates" in fr.details else {}),
            }
            kind = "field_conflict" if fr.status == CONFLICT else "low_confidence_field"
            if existing is None:
                session.add(
                    ReviewItem(
                        kind=kind,
                        vacancy_id=sp.canonical_vacancy_id,
                        source_posting_id=sp.id,
                        field=name,
                        details=details,
                    )
                )
            else:
                existing.kind, existing.details = kind, details
        elif existing is not None:
            existing.status = "resolved"
            existing.resolved_at = utcnow()
            existing.details = {**existing.details, "resolution": "auto: field is now confident"}


def reprocess_all(session: Session, *, now: datetime | None = None) -> int:
    """Re-run extraction on every latest snapshot (after improving rules). Duplicate links are kept."""
    now = now or utcnow()
    count = 0
    for sp in session.scalars(select(SourcePosting)).all():
        snap = latest_snapshot(session, sp)
        if snap is None:
            continue
        process_snapshot(session, sp, snap, now=now)
        count += 1
    return count
