"""End-to-end processing against PostgreSQL: snapshot -> extraction -> dedup -> canonical -> lifecycle."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import CanonicalVacancy, ExtractedField, RawSnapshot, ReviewItem, SourcePosting
from app.pipeline import (
    SourceDisabledError,
    UnknownSourceError,
    ensure_source,
    expire_vacancies,
    ingest_posting,
    mark_missing,
    set_source_enabled,
)
from tests.factories import NOW, SOON, data_intern, python_intern, python_intern_repost


@pytest.fixture
def sources(db):
    ensure_source(db, "hh", name="HeadHunter (test)", kind="api")
    ensure_source(db, "tg", name="Telegram (test)", kind="telegram")
    db.flush()


def test_new_posting_creates_canonical_with_extracted_fields(db, sources):
    r = ingest_posting(db, "hh", python_intern(), now=NOW)
    assert r.status == "new" and r.canonical_vacancy_id

    v = db.get(CanonicalVacancy, r.canonical_vacancy_id)
    assert v.status == "active"
    assert v.is_internship is True and v.level == "intern"
    assert v.cities == ["Almaty"] and v.work_format == "hybrid"
    assert set(v.skills) == {"Python", "SQL", "Git"}
    assert v.deadline == SOON
    assert v.salary["min"] == 150000 and v.salary["currency"] == "KZT"
    assert v.eligibility["min_year"] == 3 and v.eligibility["max_year"] == 4
    assert "<p>" not in v.description  # normalised copy; the raw HTML stays in raw_snapshots
    assert v.field_meta["deadline"]["status"] == "ok" and v.field_meta["deadline"]["evidence"]

    snap = db.scalar(select(RawSnapshot))
    assert "<p>" in snap.description and len(snap.content_hash) == 64
    assert (
        db.scalar(select(func.count()).select_from(ExtractedField).where(ExtractedField.snapshot_id == snap.id)) == 11
    )


def test_unchanged_posting_is_not_reprocessed_but_marked_checked(db, sources):
    first = ingest_posting(db, "hh", python_intern(), now=NOW)
    later = NOW + timedelta(hours=6)
    again = ingest_posting(db, "hh", python_intern(), now=later)
    assert again.status == "unchanged"
    assert db.scalar(select(func.count()).select_from(RawSnapshot)) == 1
    assert db.get(CanonicalVacancy, first.canonical_vacancy_id).last_checked_at == later


def test_changed_posting_creates_new_snapshot_and_updates_canonical(db, sources):
    first = ingest_posting(db, "hh", python_intern(), now=NOW)
    changed = python_intern(description="Стажировка Python. Офис в Астане. Работа удаленно не предусмотрена.")
    r = ingest_posting(db, "hh", changed, now=NOW + timedelta(hours=1))
    assert r.status == "changed" and r.canonical_vacancy_id == first.canonical_vacancy_id
    assert db.scalar(select(func.count()).select_from(RawSnapshot)) == 2
    v = db.get(CanonicalVacancy, r.canonical_vacancy_id)
    assert v.cities == ["Astana"] and v.work_format == "onsite"


def test_repost_on_another_source_joins_the_same_canonical(db, sources):
    a = ingest_posting(db, "hh", python_intern(), now=NOW)
    b = ingest_posting(db, "tg", python_intern_repost(), now=NOW)
    c = ingest_posting(db, "hh", data_intern(), now=NOW)
    assert a.canonical_vacancy_id == b.canonical_vacancy_id
    assert c.canonical_vacancy_id != a.canonical_vacancy_id

    links = db.scalars(select(SourcePosting).where(SourcePosting.canonical_vacancy_id == a.canonical_vacancy_id)).all()
    assert {sp.match_method for sp in links} == {"new", "auto"}
    v = db.get(CanonicalVacancy, a.canonical_vacancy_id)
    assert "Python" in v.skills and v.deadline == SOON


def test_conflicting_sources_make_field_unknown_and_open_review(db, sources):
    a = ingest_posting(db, "hh", python_intern(), now=NOW)
    other_salary = python_intern_repost(description=python_intern_repost().description.replace("150 000", "180 000"))
    b = ingest_posting(db, "tg", other_salary, now=NOW)
    assert a.canonical_vacancy_id == b.canonical_vacancy_id
    v = db.get(CanonicalVacancy, a.canonical_vacancy_id)
    assert v.salary is None and v.field_meta["salary"]["status"] == "conflict"
    item = db.scalar(select(ReviewItem).where(ReviewItem.kind == "field_conflict", ReviewItem.field == "salary"))
    assert item is not None and item.vacancy_id == v.id and len(item.details["candidates"]) == 2


def test_low_confidence_field_goes_to_review_queue(db, sources):
    p = python_intern(description="Стажировка. Заявки принимаются до конца месяца.")
    r = ingest_posting(db, "hh", p, now=NOW)
    item = db.scalar(
        select(ReviewItem).where(ReviewItem.source_posting_id == r.source_posting_id, ReviewItem.field == "deadline")
    )
    assert item is not None and item.kind == "low_confidence_field" and item.status == "open"


def test_expiry_by_deadline_and_by_disappearance(db, sources):
    r = ingest_posting(db, "hh", python_intern(), now=NOW)
    v = db.get(CanonicalVacancy, r.canonical_vacancy_id)
    assert expire_vacancies(db, NOW + timedelta(days=30)) == 1
    assert v.status == "expired" and v.expired_reason == "deadline_passed"

    r2 = ingest_posting(db, "hh", data_intern(), now=NOW)
    assert mark_missing(db, "hh", seen_external_ids=["hh-1"], now=NOW) == 1
    v2 = db.get(CanonicalVacancy, r2.canonical_vacancy_id)
    assert v2.status == "active"  # grace period
    expire_vacancies(db, NOW + timedelta(days=4))
    assert v2.status == "expired" and v2.expired_reason == "source_gone"

    ingest_posting(db, "hh", data_intern(), now=NOW + timedelta(days=5))  # it came back
    assert v2.status == "active"


def test_disabling_a_source_hides_its_vacancies(db, sources):
    r = ingest_posting(db, "hh", data_intern(), now=NOW)
    set_source_enabled(db, "hh", False, NOW)
    assert db.get(CanonicalVacancy, r.canonical_vacancy_id).status == "hidden"
    with pytest.raises(SourceDisabledError):
        ingest_posting(db, "hh", data_intern(), now=NOW)
    with pytest.raises(UnknownSourceError):
        ingest_posting(db, "nope", data_intern(), now=NOW)
    set_source_enabled(db, "hh", True, NOW)
    assert db.get(CanonicalVacancy, r.canonical_vacancy_id).status == "active"
