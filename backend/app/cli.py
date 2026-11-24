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
    args = parser.parse_args(argv)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
