"""Run one source end to end and record the run (collection, retry bookkeeping, source health).

    run_source(session, "hh_kz")

1. registers the source if needed (policy notes, interval) and refuses to run a disabled one;
2. opens a `source_runs` row (status=running, attempt n);
3. lets the adapter fetch, saving every raw HTTP response to the snapshot store;
4. hands the postings to the Part A pipeline (`ingest_batch`): snapshot, hash, extraction, dedup, canonical record;
5. if the adapter saw every live posting (full scan, complete), marks the rest as gone (`mark_missing`);
6. closes the run as success / failed with counts and the error message.

Errors are re-raised so the scheduler can decide to retry (TransientError) or not (PermanentError).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.adapters import Adapter, FetchContext, build_registry
from app.ingest.errors import CollectError, PermanentError, TransientError
from app.ingest.http import PoliteClient
from app.ingest.settings import IngestSettings, get_ingest_settings
from app.ingest.snapshots import RawResponseStore
from app.models import Source, SourceRun
from app.pipeline import ensure_source, ingest_batch, mark_missing
from app.pipeline.process import utcnow

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    source: str
    status: str
    attempt: int
    counts: dict[str, int] = field(default_factory=dict)
    marked_missing: int = 0
    requests: int = 0
    error: str | None = None
    transient: bool = False  # True if retrying later may help (timeouts, 429, 5xx)


ClientFactory = Callable[[str], PoliteClient]


def default_client_factory(settings: IngestSettings) -> ClientFactory:
    def make(source_key: str) -> PoliteClient:
        return PoliteClient(
            user_agent=settings.http_user_agent,
            store=RawResponseStore(settings.snapshot_dir, source_key),
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            min_interval=settings.http_min_interval_seconds,
        )

    return make


def register(session: Session, adapter: Adapter) -> Source:
    source = ensure_source(session, adapter.key, name=adapter.name, kind=adapter.kind, base_url=adapter.base_url)
    source.name = adapter.name
    source.kind = adapter.kind
    source.base_url = adapter.base_url
    source.fetch_interval_minutes = adapter.interval_minutes
    source.policy_notes = adapter.policy_notes
    return source


def last_success(session: Session, source: Source) -> datetime | None:
    return session.scalar(
        select(SourceRun.started_at)
        .where(SourceRun.source_id == source.id, SourceRun.status == "success")
        .order_by(SourceRun.started_at.desc())
        .limit(1)
    )


def run_source(
    session: Session,
    source_key: str,
    *,
    attempt: int = 1,
    registry: dict[str, Adapter] | None = None,
    client_factory: ClientFactory | None = None,
    limit: int | None = None,
    now: Callable[[], datetime] = utcnow,
) -> RunReport:
    registry = registry if registry is not None else build_registry()
    adapter = registry.get(source_key)
    if adapter is None:
        raise PermanentError(f"no adapter for source {source_key!r}; known: {', '.join(sorted(registry))}")
    client_factory = client_factory or default_client_factory(get_ingest_settings())

    source = register(session, adapter)
    session.commit()
    if not source.enabled:
        log.info("source %s is disabled, skipping", source_key)
        return RunReport(source_key, "skipped", attempt, error="disabled")

    run = SourceRun(source_id=source.id, started_at=now(), status="running", attempt=attempt)
    session.add(run)
    session.commit()
    report = RunReport(source_key, "running", attempt)

    ctx = FetchContext(client=client_factory(source_key), since=last_success(session, source), limit=limit)
    seen: list[str] = []
    counts: Counter[str] = Counter()
    report.counts = counts  # filled as we go, so a run that fails halfway still reports what it stored

    try:
        adapter.check_config()
        for posting in adapter.fetch(ctx):
            seen.append(posting.external_id)
            for result in ingest_batch(session, source_key, [posting]):  # commits per posting
                counts[result.status] += 1
        if adapter.full_scan and ctx.complete and limit is None:
            report.marked_missing = mark_missing(session, source_key, seen)
            session.commit()
        report.status = "success"
    except CollectError as exc:
        session.rollback()
        report.status, report.error = "failed", str(exc)
        report.transient = isinstance(exc, TransientError)
    except Exception as exc:  # unexpected bug: record it, then let the scheduler see it
        session.rollback()
        report.status, report.error = "failed", f"{exc.__class__.__name__}: {exc}"
        _finish(session, run, report, ctx, now)
        raise
    finally:
        report.requests = ctx.client.requests_made
        ctx.client.close()

    _finish(session, run, report, ctx, now)
    if report.status == "failed":
        log.warning("source %s attempt %d failed: %s", source_key, attempt, report.error)
    return report


def _finish(
    session: Session, run: SourceRun, report: RunReport, ctx: FetchContext, now: Callable[[], datetime]
) -> None:
    run = session.merge(run)
    run.finished_at = now()
    run.status = report.status
    run.fetched = sum(report.counts.values())
    run.new = report.counts.get("new", 0)
    run.changed = report.counts.get("changed", 0)
    errors = report.counts.get("error", 0)
    run.error = report.error or (f"{errors} postings failed to ingest" if errors else None)
    session.commit()


def source_health(session: Session, limit_runs: int = 5) -> list[dict]:
    """Latest runs per source, for the CLI and (Spring) the admin dashboard."""
    out = []
    for source in session.scalars(select(Source).order_by(Source.key)):
        runs = session.scalars(
            select(SourceRun)
            .where(SourceRun.source_id == source.id)
            .order_by(SourceRun.started_at.desc())
            .limit(limit_runs)
        ).all()
        out.append(
            {
                "key": source.key,
                "enabled": source.enabled,
                "interval_minutes": source.fetch_interval_minutes,
                "runs": [
                    {
                        "started_at": r.started_at,
                        "status": r.status,
                        "attempt": r.attempt,
                        "fetched": r.fetched,
                        "new": r.new,
                        "changed": r.changed,
                        "error": r.error,
                    }
                    for r in runs
                ],
            }
        )
    return out
