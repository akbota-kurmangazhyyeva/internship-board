"""Field-extraction evaluation (NFR-04: macro-F1 >= 0.85, zero fabricated deadlines/salaries).

python -m evaluation.eval_extraction                         # frozen test split
python -m evaluation.eval_extraction --data evaluation/data/dev --errors
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.extraction import EXTRACTOR_VERSION
from app.extraction.salary import salary_key
from evaluation.io import TEST_DIR, Dataset, report_path, run_extraction
from evaluation.metrics import PRF, macro_f1, set_counts, single_counts
from evaluation.schema import GoldLabel

MACRO_FIELDS = [
    "level",
    "skills",
    "cities",
    "work_format",
    "deadline",
    "salary",
    "languages",
    "eligibility",
    "apply_url",
]
EXTRA_FIELDS = ["is_internship", "posting_language"]
SET_FIELDS = {"skills", "cities", "languages"}
TARGET_MACRO_F1 = 0.85


def _url(u: str | None) -> str | None:
    if not u:
        return None
    return u.strip().rstrip("/").lower()


def gold_value(label: GoldLabel, name: str) -> Any:
    v = getattr(label, name)
    if name in SET_FIELDS:
        return {x.lower() for x in v}
    if name == "deadline":
        return v.isoformat() if v else None
    if name == "salary":
        return None if v is None else (("unpaid",) if v.unpaid else (v.min, v.max, v.currency))
    if name == "eligibility":
        return None if v is None or (v.min_year is None and v.max_year is None) else (v.min_year, v.max_year)
    if name == "apply_url":
        return _url(v)
    return v


def pred_value(public: dict[str, Any], name: str) -> Any:
    v = public.get(name)
    if name in SET_FIELDS:
        return {x.lower() for x in (v or [])}
    if name == "salary":
        return salary_key(v)
    if name == "eligibility":
        return (
            None
            if not v or (v.get("min_year") is None and v.get("max_year") is None)
            else (v["min_year"], v["max_year"])
        )
    if name == "apply_url":
        return _url(v)
    return v


def evaluate(ds: Dataset) -> dict[str, Any]:
    fields = MACRO_FIELDS + EXTRA_FIELDS
    overall: dict[str, PRF] = {f: PRF() for f in fields}
    by_lang: dict[str, dict[str, PRF]] = defaultdict(lambda: {f: PRF() for f in MACRO_FIELDS})
    fabricated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for posting, label in ds.labelled:
        result = run_extraction(posting)
        public = result.public_values()
        for name in fields:
            g, p = gold_value(label, name), pred_value(public, name)
            counts = set_counts(g, p) if name in SET_FIELDS else single_counts(g, p)
            overall[name] += counts
            if name in MACRO_FIELDS:
                by_lang[label.posting_language][name] += counts
            if counts.fp or counts.fn:
                fr = result.fields[name]
                errors.append(
                    {
                        "posting_id": posting.posting_id,
                        "field": name,
                        "gold": sorted(g) if isinstance(g, set) else g,
                        "pred": sorted(p) if isinstance(p, set) else p,
                        "status": fr.status,
                        "method": fr.method,
                        "evidence": fr.evidence,
                    }
                )
            if name in ("deadline", "salary") and g is None and p is not None:
                fabricated.append(
                    {
                        "posting_id": posting.posting_id,
                        "field": name,
                        "pred": p,
                        "evidence": result.fields[name].evidence,
                    }
                )

    macro = macro_f1({f: overall[f] for f in MACRO_FIELDS})
    return {
        "dataset": str(ds.dir),
        "frozen": ds.frozen,
        "extractor_version": EXTRACTOR_VERSION,
        "n_postings": len(ds.postings),
        "n_labelled": len(ds.labelled),
        "macro_f1": None if macro is None else round(macro, 4),
        "fields": {f: overall[f].as_dict() for f in fields},
        "by_language": {
            lang: {
                "n_fields_evaluable": sum(c.evaluable for c in prfs.values()),
                "macro_f1": None if macro_f1(prfs) is None else round(macro_f1(prfs), 4),
            }
            for lang, prfs in sorted(by_lang.items())
        },
        "fabricated": fabricated,
        "targets": {
            "macro_f1>=0.85": macro is not None and macro >= TARGET_MACRO_F1,
            "no_fabricated_deadline_or_salary": not fabricated,
        },
        "errors": errors,
    }


def render(report: dict[str, Any], show_errors: bool) -> str:
    lines = [
        f"Extraction evaluation: {report['dataset']} ({'FROZEN test set' if report['frozen'] else 'not frozen'})",
        f"extractor {report['extractor_version']} · {report['n_labelled']}/{report['n_postings']} postings labelled",
        "",
        f"{'field':18}{'P':>7}{'R':>7}{'F1':>7}{'TP':>5}{'FP':>5}{'FN':>5}",
    ]
    for name, m in report["fields"].items():
        marker = "" if name in MACRO_FIELDS else "  (not in macro)"
        lines.append(
            f"{name:18}{m['precision']:7.2f}{m['recall']:7.2f}{m['f1']:7.2f}{m['tp']:5}{m['fp']:5}{m['fn']:5}{marker}"
        )
    lines += ["", f"macro-F1: {report['macro_f1']}"]
    for lang, m in report["by_language"].items():
        lines.append(f"  {lang:6} macro-F1 {m['macro_f1']}")
    lines.append(f"fabricated deadlines/salaries: {len(report['fabricated'])}")
    for f in report["fabricated"]:
        lines.append(f"  ! {f['posting_id']} {f['field']} = {f['pred']}   [{f['evidence']}]")
    lines.append("")
    for target, ok in report["targets"].items():
        lines.append(f"{'PASS' if ok else 'FAIL'}  {target}")
    if show_errors and report["errors"]:
        lines += ["", "Errors (for error analysis):"]
        for e in report["errors"]:
            lines.append(
                f"  {e['posting_id']:>8} {e['field']:14} gold={e['gold']!r} pred={e['pred']!r} ({e['status']}, {e['method']})"
            )
            if e["evidence"]:
                lines.append(f"{'':25}{e['evidence']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=TEST_DIR)
    ap.add_argument("--errors", action="store_true", help="list every mismatch")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    ds = Dataset(args.data)
    if not ds.labelled:
        raise SystemExit("no labels yet: fill labels.jsonl first (see evaluation/README.md)")
    report = evaluate(ds)
    print(render(report, args.errors))
    if not args.no_save:
        path = report_path("extraction", args.data, "json")
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nreport: {path}")
    return 0 if all(report["targets"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
