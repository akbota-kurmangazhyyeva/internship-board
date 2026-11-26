"""Part B integration tests: a source run end to end against PostgreSQL (needs the board_test database)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
from sqlalchemy import select

from app.ingest.adapters.base import Adapter, FetchContext
from app.ingest.contract import RawPostingIn
from app.ingest.errors import TransientError
from app.ingest.http import PoliteClient
from app.ingest.runner import run_source, source_health
from app.models import CanonicalVacancy, SourcePosting, SourceRun
from tests.factories import data_intern, python_intern


class FakeAdapter(Adapter):
    key = "fake"
    name = "Fake source"
    kind = "api"
    full_scan = True
    policy_notes = "test"

    def __init__(self, postings: list[RawPostingIn], fail_after: int | None = None, complete: bool = True) -> None:
        self.postings = postings
        self.fail_after = fail_after
        self.complete = complete

    def fetch(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        for i, p in enumerate(self.postings):
            if self.fail_after is not None and i >= self.fail_after:
                raise TransientError("HTTP 503 after 3 attempts")
            yield p
        ctx.complete = self.complete


def _factory(_key: str) -> PoliteClient:
    return PoliteClient(user_agent="t", transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def _run(db, adapter, **kw):
    return run_source(db, "fake", registry={"fake": adapter}, client_factory=_factory, **kw)


def test_successful_run_is_recorded_and_ingested(db):
    report = _run(db, FakeAdapter([python_intern("1"), data_intern("2")]))
    assert report.status == "success"
    assert report.counts == {"new": 2}
    run = db.scalar(select(SourceRun).order_by(SourceRun.id.desc()))
    assert (run.status, run.fetched, run.new, run.attempt) == ("success", 2, 2, 1)
    assert run.finished_at is not None
    assert db.scalar(select(CanonicalVacancy).where(CanonicalVacancy.title.ilike("%python%"))) is not None

    again = _run(db, FakeAdapter([python_intern("1"), data_intern("2")]))
    assert again.counts == {"unchanged": 2}


def test_complete_full_scan_marks_missing_postings(db):
    _run(db, FakeAdapter([python_intern("1"), data_intern("2")]))
    report = _run(db, FakeAdapter([python_intern("1")]))
    assert report.marked_missing == 1
    gone = db.scalar(select(SourcePosting).where(SourcePosting.external_id == "2"))
    assert gone.gone_since is not None


def test_incomplete_scan_marks_nothing_missing(db):
    _run(db, FakeAdapter([python_intern("1"), data_intern("2")]))
    report = _run(db, FakeAdapter([python_intern("1")], complete=False))
    assert report.marked_missing == 0


def test_failed_run_keeps_partial_results_and_error(db):
    report = _run(db, FakeAdapter([python_intern("1"), data_intern("2")], fail_after=1), attempt=2)
    assert report.status == "failed" and report.transient
    assert report.counts == {"new": 1}
    run = db.scalar(select(SourceRun).order_by(SourceRun.id.desc()))
    assert (run.status, run.attempt, run.new) == ("failed", 2, 1)
    assert "503" in run.error
    health = {s["key"]: s for s in source_health(db)}
    assert health["fake"]["runs"][0]["status"] == "failed"


def test_disabled_source_is_skipped(db):
    from app.pipeline import set_source_enabled
    from app.pipeline.process import utcnow

    _run(db, FakeAdapter([python_intern("1")]))
    set_source_enabled(db, "fake", False, utcnow())
    db.commit()
    assert _run(db, FakeAdapter([python_intern("1")])).status == "skipped"
