"""Operational commands.

    python -m app.cli load-jsonl data/seed.jsonl --source seed_file --name "Seed dataset"
    python -m app.cli reprocess        # re-run extraction after improving rules
    python -m app.cli expire           # daily lifecycle job (FR-11)

Each JSONL line is a RawPostingIn object (see app/ingest/contract.py); unknown keys are ignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from app.db import get_sessionmaker
from app.ingest.contract import RawPostingIn
from app.pipeline import ensure_source, expire_vacancies, ingest_batch, reprocess_all
from app.pipeline.process import utcnow


def read_jsonl(path: Path) -> Iterator[RawPostingIn]:
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                try:
                    yield RawPostingIn.model_validate(json.loads(line))
                except ValueError as exc:
                    print(f"{path}:{n}: skipped invalid record: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    load = sub.add_parser("load-jsonl", help="ingest postings from a JSONL file")
    load.add_argument("path", type=Path)
    load.add_argument("--source", required=True, help="source key, e.g. seed_file or hh_kz")
    load.add_argument("--name", help="human-readable source name (when registering a new source)")
    load.add_argument("--kind", default="file")
    sub.add_parser("reprocess", help="re-run extraction and canonical merge for all postings")
    sub.add_parser("expire", help="apply lifecycle rules (deadline passed, sources gone)")
    # ---- Part B: collection
    run = sub.add_parser("run-source", help="collect one source now (same code path as the scheduler)")
    run.add_argument("key", help="source key, e.g. hh_kz, indrive_careers, seed_file")
    run.add_argument("--limit", type=int, help="stop after N postings (no postings are marked missing)")
    sub.add_parser("sources", help="list sources with their latest runs (source health)")
    for name in ("enable-source", "disable-source"):
        p = sub.add_parser(name, help=f"{name.split('-')[0]} a source; disabling hides its vacancies (FR-26)")
        p.add_argument("key")
    seed = sub.add_parser("collect-seed", help="fetch postings from a live source into a JSONL seed file (no DB)")
    seed.add_argument("key")
    seed.add_argument("--out", type=Path, required=True)
    seed.add_argument("--limit", type=int, default=100)
    conv = sub.add_parser("seed-from-csv", help="convert a manually collected CSV into seed JSONL")
    conv.add_argument("path", type=Path)
    conv.add_argument("--out", type=Path, required=True)
    merge = sub.add_parser("merge-seed", help="merge seed JSONL files, drop duplicates, print counts per source")
    merge.add_argument("paths", type=Path, nargs="+")
    merge.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.cmd in ("collect-seed", "seed-from-csv", "merge-seed"):
        return _seed_command(args)

    with get_sessionmaker()() as session:
        if args.cmd == "load-jsonl":
            ensure_source(session, args.source, name=args.name, kind=args.kind)
            session.commit()
            results = ingest_batch(session, args.source, read_jsonl(args.path))
            print(dict(Counter(r.status for r in results)))
            for r in results:
                if r.status == "error":
                    print(f"  error {r.external_id}: {r.error}", file=sys.stderr)
        elif args.cmd == "reprocess":
            n = reprocess_all(session)
            session.commit()
            print(f"reprocessed {n} postings")
        elif args.cmd == "expire":
            n = expire_vacancies(session, utcnow())
            session.commit()
            print(f"{n} vacancies changed status")
        elif args.cmd == "run-source":
            from app.ingest.runner import run_source

            report = run_source(session, args.key, limit=args.limit)
            print(
                f"{report.source}: {report.status} {dict(report.counts)} missing={report.marked_missing} "
                f"requests={report.requests}"
            )
            if report.error:
                print(f"  error: {report.error}", file=sys.stderr)
            return 0 if report.status in ("success", "skipped") else 1
        elif args.cmd == "sources":
            from app.ingest.runner import source_health

            for s in source_health(session):
                state = "enabled" if s["enabled"] else "DISABLED"
                print(f"{s['key']:<18} {state:<8} every {s['interval_minutes']} min")
                for r in s["runs"]:
                    line = f"   {r['started_at']:%Y-%m-%d %H:%M} {r['status']:<8} try {r['attempt']} "
                    line += f"fetched={r['fetched']} new={r['new']} changed={r['changed']}"
                    print(line + (f"  {r['error'][:100]}" if r["error"] else ""))
        elif args.cmd in ("enable-source", "disable-source"):
            from app.ingest.adapters import build_registry
            from app.ingest.runner import register
            from app.pipeline import set_source_enabled

            if (adapter := build_registry().get(args.key)) is not None:
                register(session, adapter)
                session.flush()
            n = set_source_enabled(session, args.key, args.cmd == "enable-source", utcnow())
            session.commit()
            print(f"{args.key}: {args.cmd.split('-')[0]}d, {n} vacancies affected")
    return 0


def _seed_command(args: argparse.Namespace) -> int:
    from app.ingest import seed_tools

    if args.cmd == "collect-seed":
        from app.ingest.adapters import FetchContext, build_registry
        from app.ingest.runner import default_client_factory
        from app.ingest.settings import get_ingest_settings

        adapter = build_registry()[args.key]
        ctx = FetchContext(client=default_client_factory(get_ingest_settings())(args.key), limit=args.limit)
        try:
            postings = list(adapter.fetch(ctx))
        finally:
            ctx.client.close()
        for p in postings:
            p.payload = {**(p.payload or {}), "collected_from": args.key}
        print(f"{args.key}: wrote {seed_tools.write_jsonl(postings, args.out)} postings to {args.out}")
    elif args.cmd == "seed-from-csv":
        postings, errors = seed_tools.csv_to_postings(args.path)
        for e in errors:
            print(f"  skipped {e}", file=sys.stderr)
        print(f"wrote {seed_tools.write_jsonl(postings, args.out)} postings to {args.out}")
    elif args.cmd == "merge-seed":
        counts = seed_tools.merge_seed(args.paths, args.out)
        for source, n in counts.most_common():
            print(f"  {source:<24} {n}")
        print(f"total {sum(counts.values())} postings → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
