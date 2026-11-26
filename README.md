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
│   │   ├── ingest/          contract.py + Part B: adapters/, http.py, snapshots.py, runner.py, seed_tools.py
│   │   ├── services/        search / filter / feed queries
│   │   ├── models.py        database schema (Alembic migrations in alembic/)
│   │   ├── worker.py        Celery scheduler: per-source jobs with retry, daily expiry (Part B)
│   │   └── cli.py           load-jsonl, reprocess, expire, run-source, sources, collect-seed, seed-from-csv
│   ├── evaluation/          frozen test set tooling and metric scripts (see evaluation/README.md)
│   ├── data/seed/           seed dataset instructions and CSV template (Part B)
│   └── tests/               unit + PostgreSQL integration tests
├── web/                     Next.js + TypeScript student web app (Part B)
├── docs/sources.md          source audit and policy matrix (Part B)
├── docker/                  Postgres init (creates the board_test database)
├── docker-compose.yml       db, api, redis, worker, beat, web
└── .github/workflows/ci.yml lint, migrations check, tests, eval smoke test, docker build
```

## Quick start

```bash
cp .env.example .env              # then set SECRET_KEY (and HH_APP_TOKEN when you have it)
docker compose up --build -d      # PostgreSQL, API, Redis, scheduler, web app; migrations run automatically
open http://localhost:3000        # student web app
open http://localhost:8000/docs   # interactive API documentation (OpenAPI)
docker compose exec api python -m app.cli run-source indrive_careers   # collect a live source right now

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

## Part B: collection and web app

**Sources** (policy matrix and decisions in [docs/sources.md](docs/sources.md)):

| Key | What | Status |
|---|---|---|
| `seed_file` | JSONL of manually collected real postings ([backend/data/seed](backend/data/seed/README.md)) | ready |
| `indrive_careers` | inDrive career site via its public WordPress REST API, Kazakhstan postings only | live, no credentials |
| `hh_kz` | hh.kz official API, area 40 | **stub mode** (6 demo postings, labelled) until `HH_APP_TOKEN` is set; then the real API |

**How a run works** (`app/ingest/runner.py`): register source → open a `source_runs` row → adapter fetches through
`PoliteClient` (User-Agent with contact, 1 request/s per host, robots.txt for non-API sources, retries 429/5xx with
backoff and Retry-After) → every raw HTTP response is saved gzip-compressed under `data/snapshots/<source>/<day>/` →
postings go to `ingest_batch` one by one → after a complete full scan, unseen postings are marked missing → the run
is closed as success/failed with counts and the error.

**Scheduler** (`app/worker.py`, Celery + Redis): one job per source at its own interval (seed 24 h, hh 6 h, career
sites 12 h) plus daily expiry at 03:10 Almaty time. A transient failure (timeout, 429, 5xx) retries the whole run up to
3 times with exponential backoff (1, 2, 4 min + jitter); a permanent one (no token, 403, robots.txt) is recorded and
not retried. A Redis lock prevents overlapping runs of one source.

```bash
python -m app.cli run-source indrive_careers   # same code path as the scheduler
python -m app.cli sources                      # source health: latest runs, errors
python -m app.cli disable-source hh_kz         # stop a source and hide its vacancies (FR-26)
```

**Web app** (`web/`, Next.js 15 + TypeScript, no UI framework): browse with search, filters and sort kept in the URL;
personal feed with fit score and reasons; vacancy detail with every field's provenance ("How we know": source field or
text rule, confidence, evidence) and all source links with last-checked time; save/unsave; profile form with
type-ahead skills and cities; consent toggle and account deletion. Unknown values are always shown as "Unknown".
Responsive down to 360 px, keyboard accessible (skip link, labels, focus styles, aria-live results).

```bash
cd web && npm install && npm run dev            # http://localhost:3000, expects the API on :8000
npm test && npm run typecheck && npm run build
```

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

## Requirements traceability (Part B)

| Requirement | Where |
|---|---|
| Source adapters, scheduled collection | `ingest/adapters/`, `worker.py::build_schedule` |
| FR-03 raw snapshots for audit | `ingest/snapshots.py` (HTTP responses) + Part A `RawSnapshot` (posting text) |
| Retry, rate limits, failure reporting | `ingest/http.py::PoliteClient`, `worker.py::collect_source`, `source_runs`, `cli sources` |
| FR-11 postings gone from a full scan | `runner.py` → `mark_missing` only after a complete scan |
| FR-14/16-22 student UI (profile, search, filters, feed, detail, saved) | `web/src/app/*` |
| NFR-11 Unknown never shown as a guess | `web/src/components/VacancyCard.tsx::Unknown`, `web/src/lib/format.ts` |
| Source policy (kickoff risk 1) | `docs/sources.md`, robots.txt check, User-Agent with contact |

Not in Part A v0: password reset and notifications (need the email/Telegram channel), admin API for the
review queue (tables and auto-resolution exist; FR-10/27 are Spring), and a language-model extractor (the
resolver already arbitrates between candidate sources, so it can be added as one more).
