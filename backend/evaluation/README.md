# Evaluation: frozen test set and metric scripts

The kickoff document requires *a frozen, manually reviewed test set that is not used to tune extraction rules,
model prompts, similarity thresholds, or ranking weights*. This folder implements that protocol.

```
evaluation/
├── data/test/     40 real postings + team labels  → FROZEN, used only to report results
├── data/dev/      the rest of the seed dataset    → use freely for error analysis and tuning
├── example/       8 synthetic postings            → file-format demo and CI smoke test only
└── reports/       JSON reports written by the scripts (git-ignored)
```

## Protocol

1. **Split** (once, after Part B delivers the seed dataset of ≥ 60 real postings):
   ```bash
   python -m evaluation.make_split path/to/seed.jsonl --n 40
   ```
   Deterministic, stratified by posting language, and all postings of one employer stay in the same split, so reposts
   can't leak between test and dev. Writes `postings.jsonl` and `labels.template.jsonl` for both splits.
2. **Label** `data/test/labels.template.jsonl`, save as `labels.jsonl`. Follow the guidelines below. Label
   **blind**: do not run the extractor or look at its output while labelling. Two people should label independently
   and resolve disagreements; note the outcome in `notes`.
3. **Ranking judgments**: write 3 to 5 personas in `profiles.jsonl` and grade every test posting for every persona in
   `judgments.jsonl` (0 = not relevant, 1 = marginal, 2 = relevant, 3 = perfect fit). Ideally the grades come from
   students matching the personas (NFR-06).
4. **Validate and freeze**:
   ```bash
   python -m evaluation.validate evaluation/data/test --expect 40
   python -m evaluation.freeze evaluation/data/test
   ```
   From then on CI fails if any test file changes. A justified correction needs
   `--refreeze --reason "..."`, which is recorded in `FROZEN.json`.
5. **Develop on dev** (`--data evaluation/data/dev --errors`, `eval_dedup --sweep`), **report on test**:
   ```bash
   python -m evaluation.eval_extraction      # NFR-04: macro-F1 ≥ 0.85, zero fabricated deadlines/salaries
   python -m evaluation.eval_dedup           # NFR-05: pairwise precision ≥ 0.95, recall ≥ 0.85
   python -m evaluation.eval_ranking         # NFR-06: beats chronological on P@10 and NDCG@10
   ```
   Each prints PASS/FAIL per target, a per-language breakdown, and writes a JSON report to `reports/`.

## Labelling guidelines

Label what the posting **states**. If it isn't stated, use `null` (or `[]`): never infer.

| Field | Value | Rules |
|---|---|---|
| `posting_language` | `kk` `ru` `en` `mixed` | `mixed` when two languages each carry real content (e.g. bilingual kk/ru) |
| `is_internship` | `true` / `false` | true for стажировка, практика, тағылымдама, intern, trainee; a junior full-time role is `false` |
| `level` | `intern` `junior` `mid` `senior` / `null` | internships are `intern`; otherwise use the title, then required experience (<3 y junior, 3 to 5 mid, 6+ senior) |
| `skills` | list | technologies and tools named anywhere, required or "a plus". Use the canonical names from `GET /api/v1/meta/filters` where they exist (aliases like "postgres" are normalised automatically); anything else is kept as written and simply counts as a miss |
| `cities` | list | cities where the work happens, canonical names (Almaty, Astana, ...). Former names map automatically (Нур-Султан → Astana). Not the HQ of a remote company |
| `work_format` | `remote` `hybrid` `onsite` / `null` | `null` if not stated or if the posting is genuinely ambiguous ("remote or office, your choice") |
| `deadline` | `YYYY-MM-DD` / `null` | **only the application deadline**: not the start date or internship period. Relative phrases ("до конца месяца") → `null`. If the year is missing, use the next occurrence after the publication date |
| `salary` | `{"min","max","currency"}` / `{"unpaid": true}` / `null` | as stated, no conversion. Exact amount → `min = max`. "от X" → `min` only; "до Y" → `max` only. "Competitive" or "by interview" → `null`. Currency `KZT` `USD` `RUB` `EUR`, or omit if not stated |
| `languages` | list of `kk` `ru` `en` | languages the candidate must or should know, including "a plus". Not the language the posting is written in |
| `eligibility` | `{"min_year","max_year"}` / `null` | year of study. "3-4 курс" → 3, 4; "с 3 курса", "3rd year and above" → 3, null. "Senior students", "final year" → `null` (+ note) |
| `apply_url` | URL / `mailto:` / `null` | where a student actually applies: a form or careers link next to "apply"; else an email address for CVs; else the posting URL itself (applying happens on the source page) |
| `duplicate_group` | string / `null` | the same internship posted several times (any source, any language) gets the same id, e.g. `"g03"`. Same company but different role, city or cohort → different internships |
| `labeler` | initials | required |

## Metric definitions

* **Single-valued fields**: a correct non-null prediction is a TP; a wrong value counts as both FP and FN; a
  prediction where gold is `null` is an FP (and, for deadline/salary, a *fabrication*); a missed value is an FN.
* **List fields** (skills, cities, languages): item-level TP/FP/FN summed over postings.
* **Macro-F1**: mean F1 over level, skills, cities, work_format, deadline, salary, languages, eligibility and
  apply_url. `is_internship` and `posting_language` are reported but not included.
* **Duplicates**: pairwise over all posting pairs in the split (gold pairs = same `duplicate_group`).
* **Ranking**: Precision@10 and Recall@10 with relevant = grade ≥ 2; NDCG@10 with gain 2^grade − 1; unjudged = 0.
  The baseline is newest-first.
