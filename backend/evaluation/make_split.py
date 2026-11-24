"""Draw the test/dev split from the seed dataset (run once, before labelling).

    python -m evaluation.make_split data/seed.jsonl --n 40

* Deterministic (fixed --random-seed), so the split can be reproduced and audited.
* Stratified by posting language, so per-language results are possible (kickoff doc, Evaluation plan).
* All postings of one employer go to the same split: reposts never leak between test and dev, and duplicate
  groups stay inside the test set where they can be labelled.
* Writes postings.jsonl for both splits and labels.template.jsonl for the labellers.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from app.dedup import employer_key
from app.extraction.normalize import normalize_text
from app.extraction.rules import detect_language
from evaluation.io import DEV_DIR, TEST_DIR, is_frozen, iter_jsonl, write_jsonl


def _template(posting_id: str) -> dict:
    return {
        "posting_id": posting_id,
        "posting_language": None,
        "is_internship": None,
        "level": None,
        "skills": [],
        "cities": [],
        "work_format": None,
        "deadline": None,
        "salary": None,
        "languages": [],
        "eligibility": None,
        "apply_url": None,
        "duplicate_group": None,
        "labeler": "",
        "notes": "",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed", type=Path, help="seed JSONL (RawPostingIn objects, from Part B)")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--random-seed", type=int, default=26)
    ap.add_argument("--test-dir", type=Path, default=TEST_DIR)
    ap.add_argument("--dev-dir", type=Path, default=DEV_DIR)
    args = ap.parse_args(argv)

    if is_frozen(args.test_dir):
        raise SystemExit(f"{args.test_dir} is frozen; a new split would invalidate it")

    rows = []
    for n, obj in iter_jsonl(args.seed):
        obj.setdefault("source", "seed")
        obj.setdefault("posting_id", f"{obj['source']}:{obj.get('external_id', n)}")
        rows.append(obj)
    if len(rows) <= args.n:
        raise SystemExit(f"only {len(rows)} postings in {args.seed}; need more than {args.n} to keep a dev split")

    groups: dict[str, list[dict]] = defaultdict(list)
    for obj in rows:
        groups[employer_key(obj.get("employer")) or f"__{obj['posting_id']}"].append(obj)

    def lang(obj: dict) -> str:
        return detect_language(normalize_text(obj.get("description") or obj.get("title", "")))[0] or "unknown"

    group_lang = {k: Counter(lang(o) for o in g).most_common(1)[0][0] for k, g in groups.items()}
    share = Counter(lang(o) for o in rows)
    quota = {lg: max(1, round(args.n * c / len(rows))) for lg, c in share.items()}

    keys = sorted(groups)
    random.Random(args.random_seed).shuffle(keys)
    test_keys: list[str] = []
    taken: Counter[str] = Counter()
    size = 0
    for k in keys:
        g, lg = groups[k], group_lang[k]
        if size + len(g) <= args.n and taken[lg] + len(g) <= quota[lg] + 1:
            test_keys.append(k)
            taken[lg] += len(g)
            size += len(g)
    for k in keys:  # top up regardless of quota if needed
        if size >= args.n:
            break
        if k not in test_keys and size + len(groups[k]) <= args.n:
            test_keys.append(k)
            size += len(groups[k])

    test = [o for k in test_keys for o in groups[k]]
    dev = [o for k in keys if k not in test_keys for o in groups[k]]
    write_jsonl(args.test_dir / "postings.jsonl", test)
    write_jsonl(args.dev_dir / "postings.jsonl", dev)
    write_jsonl(args.test_dir / "labels.template.jsonl", [_template(o["posting_id"]) for o in test])
    write_jsonl(args.dev_dir / "labels.template.jsonl", [_template(o["posting_id"]) for o in dev])
    print(
        json.dumps(
            {
                "test": len(test),
                "dev": len(dev),
                "test_languages": dict(Counter(lang(o) for o in test)),
                "dev_languages": dict(Counter(lang(o) for o in dev)),
            },
            ensure_ascii=False,
        )
    )
    print(f"next: copy {args.test_dir / 'labels.template.jsonl'} to labels.jsonl and label it (evaluation/README.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
