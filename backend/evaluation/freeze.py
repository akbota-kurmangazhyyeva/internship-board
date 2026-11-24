"""Freeze the test set: record SHA-256 hashes so any later edit is detected (CI runs `verify`).

    python -m evaluation.freeze evaluation/data/test              # first freeze (validates first)
    python -m evaluation.freeze evaluation/data/test --verify
    python -m evaluation.freeze evaluation/data/test --refreeze --reason "fixed label typo in t12, agreed 2026-12-01"

Re-freezing is allowed only with a reason, and the history is kept in FROZEN.json, because any change to
the frozen set must be documented (kickoff doc: "Major changes to ... evaluation criteria will be documented").
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.extraction import EXTRACTOR_VERSION
from evaluation.io import FILES
from evaluation.validate import validate


def file_hashes(directory: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in FILES
        if (directory / name).exists()
    }


def verify(directory: Path) -> list[str]:
    manifest_path = directory / "FROZEN.json"
    if not manifest_path.exists():
        return [f"{directory} is not frozen"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected, actual = manifest["files"], file_hashes(directory)
    problems = [f"{name} changed since freezing" for name in expected if actual.get(name) != expected[name]]
    problems += [f"{name} was added after freezing" for name in actual if name not in expected]
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--refreeze", action="store_true")
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)
    manifest_path = args.directory / "FROZEN.json"

    if args.verify:
        problems = verify(args.directory)
        for p in problems:
            print(f"FAIL  {p}")
        print("OK: frozen test set unchanged" if not problems else "the frozen test set was modified")
        return 1 if problems else 0

    history = []
    if manifest_path.exists():
        if not (args.refreeze and args.reason.strip()):
            raise SystemExit("already frozen; use --refreeze --reason '...' to record a documented change")
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        history = old.get("history", []) + [{k: old[k] for k in ("frozen_at", "files", "reason") if k in old}]

    errors, warnings = validate(args.directory)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise SystemExit("fix the errors above before freezing")

    n = sum(1 for line in (args.directory / "postings.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    manifest = {
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_postings": n,
        "extractor_version_at_freeze": EXTRACTOR_VERSION,
        "files": file_hashes(args.directory),
        "reason": args.reason or "initial freeze",
        "history": history,
        "rule": "Do not tune extraction rules, prompts, similarity thresholds or ranking weights on this set.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"frozen {n} postings -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
