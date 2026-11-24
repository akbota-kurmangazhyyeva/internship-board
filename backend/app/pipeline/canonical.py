"""Builds a canonical vacancy from all the source postings grouped into it (FR-09, FR-12).

* Text (title, employer, description) comes from the most complete live posting.
* Single-valued fields: if members agree, keep the value; if confident members disagree, the field is
  shown as Unknown and a `field_conflict` review item is opened (FR-07).
* Multi-valued fields (skills, cities, languages): union of confident values.
* The application link prefers a real link over the "apply on the source page" fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dedup import employer_key
from app.extraction.extractor import FIELD_NAMES
from app.extraction.normalize import normalize_text
from app.extraction.salary import salary_key
from app.models import CanonicalVacancy, ExtractedField, RawSnapshot, ReviewItem, Source, SourcePosting
from app.pipeline.lifecycle import apply_status

MULTI_FIELDS = {"skills", "cities", "languages"}
NO_CONFLICT_FIELDS = {"apply_url", "posting_language"}


def snapshot_fields(session: Session, snapshot_id: int) -> list[ExtractedField]:
    return list(session.scalars(select(ExtractedField).where(ExtractedField.snapshot_id == snapshot_id)))


def public_values(rows: Sequence[ExtractedField]) -> dict[str, Any]:
    """What students may see from one snapshot's extraction: confident values only."""
    out: dict[str, Any] = {name: ([] if name in MULTI_FIELDS else None) for name in FIELD_NAMES}
    for row in rows:
        if row.status == "ok":
            out[row.field] = row.value
    return out


def _compare_key(field: str, value: Any) -> Any:
    if field == "salary":
        return salary_key(value)
    if field == "eligibility" and value:
        return (value.get("min_year"), value.get("max_year"))
    return repr(value)


def _meta(row: ExtractedField, sp: SourcePosting, status: str | None = None) -> dict[str, Any]:
    return {
        "status": status or row.status,
        "confidence": row.confidence,
        "method": row.method,
        "evidence": row.evidence,
        "snapshot_id": row.snapshot_id,
        "source_posting_id": sp.id,
    }


def merge_fields(
    members: Sequence[tuple[SourcePosting, list[ExtractedField]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Returns (values, field_meta, conflicts)."""
    values: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}

    by_field: dict[str, list[tuple[SourcePosting, ExtractedField]]] = {name: [] for name in FIELD_NAMES}
    for sp, rows in members:
        for row in rows:
            if row.field in by_field:
                by_field[row.field].append((sp, row))

    for name in FIELD_NAMES:
        entries = by_field[name]
        confident = [(sp, row) for sp, row in entries if row.status == "ok"]
        if name in MULTI_FIELDS:
            merged = sorted({item for _, row in confident for item in (row.value or [])})
            values[name] = merged
            if confident:
                sp, row = min(confident, key=lambda e: e[1].confidence)
                meta[name] = _meta(row, sp)
            elif entries:
                sp, row = max(entries, key=lambda e: e[1].confidence)
                meta[name] = _meta(row, sp)
            continue

        if name == "apply_url":
            confident.sort(key=lambda e: (e[1].method == "fallback:posting_url", -e[1].confidence))
        else:
            confident.sort(key=lambda e: -e[1].confidence)

        distinct: dict[Any, tuple[SourcePosting, ExtractedField]] = {}
        for sp, row in confident:
            distinct.setdefault(_compare_key(name, row.value), (sp, row))

        if len(distinct) > 1 and name not in NO_CONFLICT_FIELDS:
            values[name] = None
            sp, row = confident[0]
            meta[name] = {**_meta(row, sp, "conflict"), "method": "conflict_between_sources"}
            conflicts[name] = [
                {"value": r.value, "confidence": r.confidence, "source_posting_id": s.id} for s, r in distinct.values()
            ]
        elif confident:
            sp, row = confident[0]
            values[name] = row.value
            meta[name] = _meta(row, sp)
        else:
            values[name] = None
            if entries:
                sp, row = max(entries, key=lambda e: e[1].confidence)
                meta[name] = _meta(row, sp)
    return values, meta, conflicts


def recompute_canonical(session: Session, vacancy: CanonicalVacancy, now: datetime) -> None:
    members = list(session.scalars(select(SourcePosting).where(SourcePosting.canonical_vacancy_id == vacancy.id)))
    if not members:
        vacancy.status = "hidden"
        vacancy.expired_reason = "no_sources"
        return

    enabled = {
        s.id for s in session.scalars(select(Source).where(Source.id.in_({m.source_id for m in members}))) if s.enabled
    }
    usable = [m for m in members if m.source_id in enabled]
    live = [m for m in usable if m.gone_since is None]
    basis = live or usable or members

    snaps: dict[int, RawSnapshot] = {}
    rows: dict[int, list[ExtractedField]] = {}
    for m in members:
        snap = session.scalar(
            select(RawSnapshot).where(RawSnapshot.source_posting_id == m.id, RawSnapshot.content_hash == m.content_hash)
        )
        if snap is not None:
            snaps[m.id] = snap
            rows[m.id] = snapshot_fields(session, snap.id)
    basis = [m for m in basis if m.id in snaps]
    if not basis:
        return

    rep = max(basis, key=lambda m: len(snaps[m.id].description or ""))
    rep_snap = snaps[rep.id]
    vacancy.title = normalize_text(rep_snap.title)
    vacancy.employer_name = rep_snap.employer or next(
        (snaps[m.id].employer for m in basis if snaps[m.id].employer), None
    )
    vacancy.employer_key = employer_key(vacancy.employer_name)
    vacancy.description = normalize_text(rep_snap.description)

    published = [snaps[m.id].published_at for m in basis if snaps[m.id].published_at]
    vacancy.published_at = min(published) if published else min(m.first_seen_at for m in basis)
    vacancy.first_seen_at = min(m.first_seen_at for m in members)
    vacancy.last_checked_at = max(m.last_checked_at for m in members)

    values, meta, conflicts = merge_fields([(m, rows[m.id]) for m in basis])
    vacancy.posting_language = values["posting_language"]
    vacancy.is_internship = values["is_internship"]
    vacancy.level = values["level"]
    vacancy.work_format = values["work_format"]
    vacancy.cities = values["cities"]
    vacancy.skills = values["skills"]
    vacancy.languages = values["languages"]
    vacancy.deadline = datetime.fromisoformat(values["deadline"]).date() if values["deadline"] else None
    vacancy.salary = values["salary"]
    vacancy.eligibility = values["eligibility"]
    vacancy.apply_url = values["apply_url"]
    vacancy.field_meta = meta
    vacancy.search_document = " \n".join(
        filter(None, [vacancy.employer_name, " ".join(vacancy.skills), " ".join(vacancy.cities), vacancy.description])
    )

    _sync_conflict_reviews(session, vacancy, conflicts)
    apply_status(vacancy, members, enabled, now)
    session.flush()


def _sync_conflict_reviews(
    session: Session, vacancy: CanonicalVacancy, conflicts: dict[str, list[dict[str, Any]]]
) -> None:
    open_items = {
        item.field: item
        for item in session.scalars(
            select(ReviewItem).where(
                ReviewItem.vacancy_id == vacancy.id,
                ReviewItem.kind == "field_conflict",
                ReviewItem.source_posting_id.is_(None),
                ReviewItem.status == "open",
            )
        )
    }
    for name, candidates in conflicts.items():
        if name in open_items:
            open_items[name].details = {"candidates": candidates, "scope": "between_sources"}
        else:
            session.add(
                ReviewItem(
                    kind="field_conflict",
                    vacancy_id=vacancy.id,
                    field=name,
                    details={"candidates": candidates, "scope": "between_sources"},
                )
            )
    for name, item in open_items.items():
        if name not in conflicts:
            item.status = "resolved"
            item.details = {**item.details, "resolution": "auto: sources agree now"}
