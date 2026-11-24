"""Check a labelled dataset before freezing it.

python -m evaluation.validate evaluation/data/test
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.extraction.vocab import normalize_skill
from evaluation.io import iter_jsonl
from evaluation.schema import EvalPosting, EvalProfile, GoldLabel, Judgment


def validate(directory: Path, expected_n: int | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def parse(name: str, model):
        path = directory / name
        items = []
        if not path.exists():
            return items
        for n, obj in iter_jsonl(path):
            try:
                items.append(model.model_validate(obj))
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err["loc"])
                    errors.append(
                        f"{name}:{n} {obj.get('posting_id') or obj.get('profile_id') or ''} {loc}: {err['msg']}"
                    )
        return items

    postings = parse("postings.jsonl", EvalPosting)
    labels = parse("labels.jsonl", GoldLabel)
    profiles = parse("profiles.jsonl", EvalProfile)
    judgments = parse("judgments.jsonl", Judgment)

    if not postings:
        errors.append("postings.jsonl is missing or empty")
    posting_ids = [p.posting_id for p in postings]
    for pid, c in Counter(posting_ids).items():
        if c > 1:
            errors.append(f"posting_id {pid} appears {c} times in postings.jsonl")
    if expected_n is not None and len(postings) != expected_n:
        warnings.append(f"{len(postings)} postings, expected {expected_n}")

    label_ids = [g.posting_id for g in labels]
    for pid, c in Counter(label_ids).items():
        if c > 1:
            errors.append(f"posting {pid} is labelled {c} times")
    for pid in sorted(set(posting_ids) - set(label_ids)):
        errors.append(f"posting {pid} has no label")
    for pid in sorted(set(label_ids) - set(posting_ids)):
        errors.append(f"label for unknown posting {pid}")

    for g in labels:
        for s in g.skills:
            if normalize_skill(s) is None:
                warnings.append(f"{g.posting_id}: skill {s!r} is not in the vocabulary (it will count as a miss)")
        if (
            g.eligibility
            and g.eligibility.min_year
            and g.eligibility.max_year
            and g.eligibility.min_year > g.eligibility.max_year
        ):
            errors.append(f"{g.posting_id}: eligibility min_year > max_year")
        if g.salary and g.salary.min is not None and g.salary.max is not None and g.salary.min > g.salary.max:
            errors.append(f"{g.posting_id}: salary min > max")
    groups = Counter(g.duplicate_group for g in labels if g.duplicate_group)
    for grp, c in groups.items():
        if c == 1:
            warnings.append(f"duplicate_group {grp!r} has a single member; use null for postings without duplicates")
    if labels and not groups:
        warnings.append("no duplicate groups labelled: duplicate-detection recall cannot be measured on this split")

    profile_ids = {p.profile_id for p in profiles}
    for j in judgments:
        if j.profile_id not in profile_ids:
            errors.append(f"judgment for unknown profile {j.profile_id}")
        if j.posting_id not in set(posting_ids):
            errors.append(f"judgment for unknown posting {j.posting_id}")
    for pid in sorted(profile_ids):
        judged = {j.posting_id for j in judgments if j.profile_id == pid}
        if len(judged) < len(posting_ids):
            warnings.append(
                f"profile {pid}: {len(judged)}/{len(posting_ids)} postings judged (unjudged count as not relevant)"
            )
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--expect", type=int, default=None, help="expected number of postings (40 for the test split)")
    args = ap.parse_args(argv)
    errors, warnings = validate(args.directory, args.expect)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR:   {e}")
    print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
