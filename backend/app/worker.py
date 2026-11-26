"""Scheduler and workers (Celery + Redis).

    celery -A app.worker worker --loglevel=info      # runs collection jobs
    celery -A app.worker beat --loglevel=info        # puts jobs on the queue on schedule

Schedule (built from the source registry, so a new adapter is scheduled automatically):
  * collect:<source>  every adapter.interval_minutes (seed file daily, hh.kz every 6 h, career sites every 12 h)
  * expire-vacancies  daily at 03:10 Asia/Almaty (FR-11)

Retry policy: a run that fails with a TransientError (timeouts, 429, 5xx) is retried up to
COLLECT_MAX_RETRIES times with exponential backoff (60 s, 120 s, 240 s, + jitter). A PermanentError (no token,
403, robots.txt) is recorded in source_runs and not retried. Inside a run, single HTTP requests are also retried
(PoliteClient). A Redis lock makes sure two runs of the same source never overlap.
"""

from __future__ import annotations

import contextlib
import logging
import random
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from app.db import get_sessionmaker
from app.ingest.adapters import build_registry
from app.ingest.runner import RunReport, run_source
from app.ingest.settings import get_ingest_settings
from app.pipeline import expire_vacancies
from app.pipeline.process import utcnow

log = logging.getLogger(__name__)
settings = get_ingest_settings()

celery_app = Celery("internship_board", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    timezone="Asia/Almaty",
    enable_utc=True,
    task_acks_late=True,  # a job is lost only if it finishes; a crashed worker's job is redelivered
    worker_prefetch_multiplier=1,
    task_default_queue="collect",
    broker_connection_retry_on_startup=True,
)


def retry_delay(retries: int, base: int | None = None) -> int:
    """Exponential backoff with jitter: base, 2*base, 4*base ... (+ up to 20%)."""
    base = base or settings.collect_retry_base_seconds
    delay = base * (2**retries)
    return int(delay + random.uniform(0, delay * 0.2))


def should_retry(report: RunReport, retries: int, max_retries: int | None = None) -> bool:
    max_retries = settings.collect_max_retries if max_retries is None else max_retries
    return report.status == "failed" and report.transient and retries < max_retries


def _lock(key: str, ttl_seconds: int):
    import redis  # imported lazily so unit tests don't need a Redis server

    client = redis.Redis.from_url(settings.redis_url)
    return client.lock(f"lock:collect:{key}", timeout=ttl_seconds, blocking=False)


@celery_app.task(bind=True, name="collect_source", max_retries=None)
def collect_source(self, source_key: str) -> dict:
    registry = build_registry()
    adapter = registry.get(source_key)
    ttl = max(60, (adapter.interval_minutes if adapter else 60) * 60)
    lock = _lock(source_key, ttl)
    if not lock.acquire():
        log.info("collect %s: previous run still in progress, skipping", source_key)
        return {"source": source_key, "status": "skipped", "reason": "locked"}
    try:
        with get_sessionmaker()() as session:
            report = run_source(session, source_key, attempt=self.request.retries + 1, registry=registry)
    finally:
        with contextlib.suppress(Exception):  # lock already expired: nothing to release
            lock.release()
    if should_retry(report, self.request.retries):
        countdown = retry_delay(self.request.retries)
        log.warning("collect %s failed (%s); retry in %ss", source_key, report.error, countdown)
        raise self.retry(countdown=countdown)
    return {"source": source_key, "status": report.status, "counts": dict(report.counts), "error": report.error}


@celery_app.task(name="expire_vacancies")
def expire_task() -> int:
    with get_sessionmaker()() as session:
        n = expire_vacancies(session, utcnow())
        session.commit()
    return n


def build_schedule() -> dict:
    schedule: dict = {
        "expire-vacancies": {"task": "expire_vacancies", "schedule": crontab(hour=3, minute=10)},
    }
    for key, adapter in build_registry().items():
        schedule[f"collect:{key}"] = {
            "task": "collect_source",
            "schedule": timedelta(minutes=adapter.interval_minutes),
            "args": (key,),
        }
    return schedule


celery_app.conf.beat_schedule = build_schedule()
