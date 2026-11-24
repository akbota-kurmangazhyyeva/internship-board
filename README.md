# Internship Board for Students in Kazakhstan

Senior project, Team 26. Collects internship postings from approved sources, structures and de-duplicates them,
and ranks them for each student with explanations.

```
internship-board/
├── backend/                 Python 3.11+, FastAPI, SQLAlchemy 2, PostgreSQL 16
│   ├── app/
│   │   ├── api/             REST API v0 (/api/v1/...)
│   │   ├── extraction/      field extraction: rules, vocabularies, confidence + provenance
│   │   ├── dedup/           duplicate detection and canonical grouping (pure functions)
│   │   ├── ranking/         explainable fit score (pure functions)
│   │   ├── pipeline/        snapshot → extract → dedup → canonical vacancy → lifecycle
│   │   ├── ingest/          contract.py: what source adapters hand to the pipeline
│   │   ├── services/        search / filter / feed queries
│   │   ├── models.py        database schema (Alembic migrations in alembic/)
│   │   └── cli.py           load-jsonl, reprocess, expire
│   ├── evaluation/          frozen test set tooling and metric scripts (see evaluation/README.md)
│   └── tests/               unit + PostgreSQL integration tests
├── docker/                  Postgres init (creates the board_test database)
├── docker-compose.yml       db + api (Part B adds redis, worker, beat, web)
└── .github/workflows/ci.yml lint, migrations check, tests, eval smoke test, docker build
```

## Quick start

```bash
cp .env.example .env              # then set SECRET_KEY
docker compose up --build -d      # PostgreSQL + API, migrations run automatically
open http://localhost:8000/docs   # interactive API documentation (OpenAPI)

# load postings from a JSONL file (one RawPostingIn per line)
docker compose exec api python -m app.cli load-jsonl evaluation/example/postings.jsonl --source example --name "Synthetic example"
```

Local development without the API container:

```bash
make setup        # backend/.venv with all dependencies
make db           # PostgreSQL only
make migrate      # apply migrations to the dev database
make test         # 160+ tests; integration tests use the board_test database
make lint
cd backend && .venv/bin/uvicorn app.main:app --reload
```

## Part A ↔ Part B contracts

**Ingestion (Part B adapters → Part A pipeline).** An adapter only converts its source into
`RawPostingIn` objects ([backend/app/ingest/contract.py](backend/app/ingest/contract.py)) and calls:

```python
from app.pipeline import ensure_source, ingest_batch, mark_missing, expire_vacancies

ensure_source(session, "hh_kz", name="HeadHunter", kind="api")   # once; sources must be registered
results = ingest_batch(session, "hh_kz", postings)              # commits per posting; errors don't stop the run
mark_missing(session, "hh_kz", seen_external_ids)               # only for full-scan sources
expire_vacancies(session, now)                                  # daily
```

The pipeline stores the raw snapshot and content hash, skips unchanged postings, extracts fields, groups
duplicates, rebuilds the canonical vacancy and opens review items. Structured data the source already has
(hh.kz `salary`, `area`, `key_skills`, `experience`, `employment`, ...) goes in `source_fields` and outranks
free-text rules. The seed file adapter can be as small as `python -m app.cli load-jsonl seed.jsonl --source seed_file`.

**API (Part A → web app).** Base path `/api/v1`; the full schema is at `/docs` and `/openapi.json`.

| Endpoint | Purpose |
|---|---|
| `POST /auth/register`, `POST /auth/login` | returns a bearer token |
| `GET /vacancies` | list, search (`q`), filters (`skill`, `city`, `work_format`, `level`, `language`, `deadline_from/to`, `internship_only`), `sort` = relevance / newest / deadline / fit, `limit`/`offset` |
| `GET /vacancies/{id}` | detail: structured fields with status/confidence/evidence, original text, all source links, application link |
| `GET /feed` | personalised ranked feed with reasons; `relaxed=true` when nothing meets the hard constraints |
| `GET/PUT /me/profile` | student profile (cities and skills accept aliases such as "Алматы" or "postgres") |
| `GET /me/saved`, `PUT/DELETE /me/saved/{id}` | saved list, ordered by deadline |
| `POST /me/interactions` | `dismiss` / `not_relevant` (always stored) and `view` / `click_apply` (only with consent) |
| `PUT /me/consent`, `GET/DELETE /me` | consent, account, deletion of all personal data |
| `GET /meta/filters` | city, skill, level, format and language values for forms |

Unknown values are `null` (or `[]`) in cards. The UI should render them as "Unknown", never as a guess (FR-07, NFR-11).

## How the intelligence works

* **Extraction** ([app/extraction](backend/app/extraction)): Kazakh/Russian/English rules for level, internship vs.
  junior role, skills, cities (incl. former names, e.g. Нур-Султан → Astana), work format, deadline, salary (as stated,
  no conversion), language requirements, study-year eligibility, application link and posting language. Every field
  stores value, confidence, method and an evidence snippet. Below 0.6 confidence, or with contradicting evidence,
  the field is Unknown and goes to the review queue. A deadline needs an explicit cue ("срок подачи", "apply by",
  "... дейін") next to the date, so internship periods and start dates are never mistaken for deadlines.
* **Duplicates** ([app/dedup](backend/app/dedup)): blocking on normalised employer / application link / publication
  window, then title tokens (with a ru/kk/en synonym map), character n-grams over transliterated text and skill
  overlap. Different known cities, deadlines or levels veto a merge (precision first). Scores between the review and
  merge thresholds open a `suspected_duplicate` review item instead of merging.
* **Ranking** ([app/ranking](backend/app/ranking)): hard constraints (level, format, city unless remote or
  relocating, study year), then a weighted score (skills 40%, interests 15%, location 15%, format 10%, study year 10%,
  language 5%, freshness 5%) with reasons such as "4 of 6 skills match · Almaty · Remote". Unknown fields never
  exclude a vacancy.

Thresholds and weights are initial values. Tune them on the **dev** split only (see evaluation/README.md).

## Requirements traceability (Part A)

| Requirement | Where |
|---|---|
| FR-03 snapshot, hash, change detection | `pipeline/process.py::ingest_posting`, `RawSnapshot` |
| FR-05/06/07 normalise, extract, confidence, Unknown, review | `extraction/`, `pipeline/process.py::_queue_field_reviews` |
| FR-08/09 blocking, similarity, canonical groups | `dedup/matcher.py`, `pipeline/canonical.py` |
| FR-11/12 lifecycle, sources and last-checked | `pipeline/lifecycle.py`, `GET /vacancies/{id}` |
| FR-13/14/15 accounts, profile, consent, deletion | `api/auth.py`, `api/me.py` |
| FR-16/17/18 multilingual search, filters, sorts, detail | `services/vacancies.py`, `models.py::SEARCH_VECTOR_SQL` |
| FR-19/20/21 ranked feed, reasons, feedback | `ranking/scorer.py`, `GET /feed`, `POST /me/interactions` |
| FR-22 saved list by deadline | `api/me.py` |
| FR-26 disable a source → hide its vacancies | `pipeline/lifecycle.py::set_source_enabled` |
| NFR-04/05/06 evaluation targets | `evaluation/eval_*.py` |
| NFR-09 Argon2 hashing, secrets from env | `security.py`, `config.py` |
| NFR-12/13 CI, Docker Compose | `.github/workflows/ci.yml`, `docker-compose.yml` |
| NFR-16 / DR-03..07 Kazakh, Russian, English; UTC+5 | `extraction/vocab.py`, `extraction/dates.py`, `config.py::KZ_TZ` |

Not in Part A v0: password reset and notifications (need the email/Telegram channel), admin API for the
review queue (tables and auto-resolution exist; FR-10/27 are Spring), and a language-model extractor (the
resolver already arbitrates between candidate sources, so it can be added as one more).
