# Common commands. Python commands run from backend/ inside its virtualenv.
PY := cd backend && .venv/bin/python
.PHONY: setup up down db test lint fmt migrate migration seed eval-example eval

setup:            ## create backend virtualenv and install dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

up:               ## start PostgreSQL + API (http://localhost:8000/docs)
	docker compose up --build -d

down:
	docker compose down

db:               ## start only PostgreSQL (for local development and tests)
	docker compose up -d db

test:             ## unit + integration tests (needs `make db`)
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check . --fix && .venv/bin/ruff format .

migrate:          ## apply migrations to the dev database
	cd backend && .venv/bin/alembic upgrade head

migration:        ## autogenerate a migration: make migration m="add notifications"
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

seed:             ## load a JSONL file: make seed file=data/seed.jsonl source=seed_file
	$(PY) -m app.cli load-jsonl $(file) --source $(source)

eval-example:     ## run all metric scripts on the synthetic example
	$(PY) -m evaluation.eval_extraction --data evaluation/example --errors --no-save; \
	$(PY) -m evaluation.eval_dedup --data evaluation/example --no-save; \
	$(PY) -m evaluation.eval_ranking --data evaluation/example --no-save

eval:             ## the real thing: frozen test set
	$(PY) -m evaluation.freeze evaluation/data/test --verify && \
	$(PY) -m evaluation.eval_extraction && $(PY) -m evaluation.eval_dedup && $(PY) -m evaluation.eval_ranking
