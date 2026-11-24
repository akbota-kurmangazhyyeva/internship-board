"""Duplicate-detection evaluation (NFR-05: pairwise precision >= 0.95, recall >= 0.85).

python -m evaluation.eval_dedup                                        # frozen test split, configured thresholds
python -m evaluation.eval_dedup --data evaluation/data/dev --sweep     # threshold sweep, DEV ONLY
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.dedup import DedupRecord, cluster
from app.extraction.normalize import normalize_text
from evaluation.io import TEST_DIR, Dataset, report_path, run_extraction
from evaluation.metrics import pairwise

TARGET_P, TARGET_R = 0.95, 0.85


def records(ds: Dataset) -> list[DedupRecord]:
    out = []
    for p, _ in ds.labelled:
        pub = run_extraction(p).public_values()
        out.append(
            DedupRecord(
                id=p.posting_id,
                title=p.title,
                description=normalize_text(p.description),
                employer=p.employer,
                published_at=p.published_at,
                cities=pub["cities"],
                level=pub["level"],
                deadline=date.fromisoformat(pub["deadline"]) if pub["deadline"] else None,
                skills=pub["skills"],
                apply_url=pub["apply_url"],
            )
        )
    return out


def evaluate(ds: Dataset, recs: list[DedupRecord], merge: float, review: float, window: int) -> dict[str, Any]:
    pred = cluster(recs, merge_threshold=merge, review_threshold=review, window_days=window)
    gold = {pid: label.duplicate_group for pid, label in ds.labels.items() if pid in pred}
    prf, fps, fns = pairwise(gold, pred)
    titles = {p.posting_id: p.title for p in ds.postings}
    gold_pairs = prf.tp + prf.fn
    return {
        "dataset": str(ds.dir),
        "frozen": ds.frozen,
        "thresholds": {"merge": merge, "review": review, "window_days": window},
        "n_postings": len(recs),
        "gold_duplicate_pairs": gold_pairs,
        "pairwise": prf.as_dict(),
        "false_merges": [{"a": a, "b": b, "titles": [titles.get(a), titles.get(b)]} for a, b in fps],
        "missed_duplicates": [{"a": a, "b": b, "titles": [titles.get(a), titles.get(b)]} for a, b in fns],
        "targets": {
            "precision>=0.95": prf.precision >= TARGET_P,
            "recall>=0.85": gold_pairs > 0 and prf.recall >= TARGET_R,
        },
    }


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=TEST_DIR)
    ap.add_argument("--merge", type=float, default=s.dedup_merge_threshold)
    ap.add_argument("--review", type=float, default=s.dedup_review_threshold)
    ap.add_argument("--window", type=int, default=s.dedup_window_days)
    ap.add_argument("--sweep", action="store_true", help="try merge thresholds 0.50..0.95 (dev split only)")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    ds = Dataset(args.data)
    if not ds.labelled:
        raise SystemExit("no labels yet: fill labels.jsonl first (see evaluation/README.md)")
    recs = records(ds)

    if args.sweep:
        if ds.frozen:
            raise SystemExit("refusing to sweep thresholds on the frozen test set: tune on evaluation/data/dev")
        print(f"{'merge':>6}{'P':>7}{'R':>7}{'F1':>7}{'FP':>5}{'FN':>5}")
        for i in range(10, 20):
            t = i * 0.05
            m = evaluate(ds, recs, t, min(args.review, t), args.window)["pairwise"]
            print(f"{t:6.2f}{m['precision']:7.2f}{m['recall']:7.2f}{m['f1']:7.2f}{m['fp']:5}{m['fn']:5}")
        return 0

    report = evaluate(ds, recs, args.merge, args.review, args.window)
    m = report["pairwise"]
    print(f"Duplicate detection: {report['dataset']} ({'FROZEN test set' if report['frozen'] else 'not frozen'})")
    print(
        f"thresholds {report['thresholds']} · {report['n_postings']} postings · {report['gold_duplicate_pairs']} gold duplicate pairs"
    )
    print(
        f"pairwise P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} (TP {m['tp']}, FP {m['fp']}, FN {m['fn']})"
    )
    for fp in report["false_merges"]:
        print(f"  false merge: {fp['a']} + {fp['b']}  {fp['titles']}")
    for fn in report["missed_duplicates"]:
        print(f"  missed:      {fn['a']} + {fn['b']}  {fn['titles']}")
    if report["gold_duplicate_pairs"] == 0:
        print("  note: the labels contain no duplicate groups, so recall cannot be measured")
    for target, ok in report["targets"].items():
        print(f"{'PASS' if ok else 'FAIL'}  {target}")
    if not args.no_save:
        path = report_path("dedup", args.data, "json")
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nreport: {path}")
    return 0 if all(report["targets"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
