# Seed dataset (≥ 60 real postings)

The seed dataset feeds the evaluation split (`evaluation/make_split.py`: 40 test, the rest dev) and the demo.
Every line of `postings.jsonl` is one `RawPostingIn` (see `app/ingest/contract.py`).

## How to build it (about 4 hours, split across the team)

1. **Live source, automatic** (run on your own laptop; needs internet):
   ```bash
   cd backend
   python -m app.cli collect-seed indrive_careers --limit 40 --out data/seed/indrive.jsonl
   python -m app.cli collect-seed hh_kz --limit 60 --out data/seed/hh.jsonl          # once HH_APP_TOKEN is set
   ```
2. **Manual** (Telegram channels, LinkedIn, Career & Advising emails): copy `manual_template.csv` into a shared Google
   Sheet, one row per posting, with the **full original text** and the **original link**. Aim for Kazakh, Russian and
   English postings, and include the same internship posted in two places (we need duplicate pairs). Export as CSV, then:
   ```bash
   python -m app.cli seed-from-csv data/seed/manual.csv --out data/seed/manual.jsonl
   ```
3. **Merge** (drops exact duplicates, prints counts per source for the report):
   ```bash
   python -m app.cli merge-seed data/seed/indrive.jsonl data/seed/hh.jsonl data/seed/manual.jsonl --out data/seed/postings.jsonl
   ```
4. **Load** it (the scheduler also re-reads it daily as source `seed_file`):
   ```bash
   python -m app.cli run-source seed_file
   ```
5. Hand `postings.jsonl` to Part A for the frozen split: `python -m evaluation.make_split data/seed/postings.jsonl --n 40`.

Targets: at least 60 postings; at least 10 in Kazakh or bilingual; at least 8 duplicate pairs across sources; at least
15 with an explicit deadline and 15 without (so "Unknown" is tested too).
