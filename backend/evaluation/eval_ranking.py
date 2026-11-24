"""Ranking evaluation (NFR-06: the personalised feed beats a chronological baseline on P@10 and NDCG@10).

    python -m evaluation.eval_ranking [--data DIR] [--k 10]

Each persona in profiles.jsonl is ranked against every posting in the split, with fields taken from the
extractor (as in production). Relevance: grade >= 2 in judgments.jsonl; unjudged postings count as grade 0.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.ranking import Profile, VacancyView, rank
from evaluation.io import TEST_DIR, Dataset, report_path, run_extraction
from evaluation.metrics import mean, ndcg_at_k, precision_at_k, recall_at_k

RELEVANT_GRADE = 2


def views(ds: Dataset) -> list[VacancyView]:
    out = []
    for p in ds.postings:
        pub = run_extraction(p).public_values()
        out.append(
            VacancyView(
                id=p.posting_id,
                title=p.title,
                description=p.description,
                skills=pub["skills"],
                cities=pub["cities"],
                work_format=pub["work_format"],
                level=pub["level"],
                languages=pub["languages"],
                eligibility=pub["eligibility"],
                deadline=date.fromisoformat(pub["deadline"]) if pub["deadline"] else None,
                published_at=p.published_at,
            )
        )
    return out


def evaluate(ds: Dataset, k: int) -> dict[str, Any]:
    vs = views(ds)
    today = ds.reference_date()
    chronological = [
        v.id for v in sorted(vs, key=lambda v: v.published_at.timestamp() if v.published_at else 0, reverse=True)
    ]
    per_profile = []
    for prof in ds.profiles:
        grades = {j.posting_id: j.grade for j in ds.judgments if j.profile_id == prof.profile_id}
        relevant = {pid for pid, g in grades.items() if g >= RELEVANT_GRADE}
        profile = Profile(**{f: getattr(prof, f) for f in Profile.__dataclass_fields__ if hasattr(prof, f)})
        personalised = [fit.vacancy_id for fit in rank(profile, vs, today).items]
        row = {"profile_id": prof.profile_id, "n_judged": len(grades), "n_relevant": len(relevant)}
        for name, ranking in (("personalised", personalised), ("chronological", chronological)):
            row[name] = {
                f"P@{k}": precision_at_k(ranking, relevant, k),
                f"R@{k}": recall_at_k(ranking, relevant, k),
                f"NDCG@{k}": ndcg_at_k(ranking, grades, k),
            }
        per_profile.append(row)

    summary = {
        system: {m: mean(r[system][m] for r in per_profile) for m in (f"P@{k}", f"R@{k}", f"NDCG@{k}")}
        for system in ("personalised", "chronological")
    }

    def beats(metric: str) -> bool:
        a, b = summary["personalised"][metric], summary["chronological"][metric]
        return a is not None and b is not None and a > b

    return {
        "dataset": str(ds.dir),
        "frozen": ds.frozen,
        "k": k,
        "reference_date": today.isoformat(),
        "profiles": per_profile,
        "summary": summary,
        "targets": {f"P@{k} > baseline": beats(f"P@{k}"), f"NDCG@{k} > baseline": beats(f"NDCG@{k}")},
    }


def _fmt(v: float | None) -> str:
    return "  n/a" if v is None else f"{v:5.3f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=TEST_DIR)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args(argv)

    ds = Dataset(args.data)
    if not ds.profiles or not ds.judgments:
        raise SystemExit("profiles.jsonl and judgments.jsonl are needed (see evaluation/README.md)")
    report = evaluate(ds, args.k)
    k = args.k
    print(f"Ranking evaluation: {report['dataset']} ({'FROZEN test set' if report['frozen'] else 'not frozen'}), k={k}")
    print(f"{'profile':10}{'judged':>7}{'rel':>5}  {'personalised P/R/NDCG':>24}  {'chronological P/R/NDCG':>24}")
    for r in report["profiles"]:
        p, c = r["personalised"], r["chronological"]
        print(
            f"{r['profile_id']:10}{r['n_judged']:7}{r['n_relevant']:5}  "
            f"{_fmt(p[f'P@{k}'])} {_fmt(p[f'R@{k}'])} {_fmt(p[f'NDCG@{k}'])}      "
            f"{_fmt(c[f'P@{k}'])} {_fmt(c[f'R@{k}'])} {_fmt(c[f'NDCG@{k}'])}"
        )
    for system, m in report["summary"].items():
        print(f"mean {system:14} P@{k} {_fmt(m[f'P@{k}'])}  R@{k} {_fmt(m[f'R@{k}'])}  NDCG@{k} {_fmt(m[f'NDCG@{k}'])}")
    if len(ds.postings) <= k:
        print(
            f"note: only {len(ds.postings)} postings <= k={k}: every system returns all of them, so P@{k} cannot differ"
        )
    for target, ok in report["targets"].items():
        print(f"{'PASS' if ok else 'FAIL'}  {target}")
    if not args.no_save:
        path = report_path("ranking", args.data, "json")
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nreport: {path}")
    return 0 if all(report["targets"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
