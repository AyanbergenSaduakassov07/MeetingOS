# MeetingOS task runner. `just --list` shows everything.

venv := ".venv"
py := venv / "bin" / "python"
port := "8470"

# Install Python (uv) and JS (bun) dependencies
setup:
    uv venv -q -p 3.13 {{ venv }}
    uv pip install -q -p {{ venv }} -r backend/requirements.txt pytest pytest-asyncio ruff
    bun install
    @test -f .env || cp .env.example .env
    @echo "Ready. Edit .env, then: just dev"

# API on :{{ port }} + web UI on :5173, both with reload
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ py }} -m uvicorn backend.main:app --reload --port {{ port }} &
    trap 'kill $!' EXIT
    cd web && bun run dev

# API only
dev-api:
    {{ py }} -m uvicorn backend.main:app --reload --port {{ port }}

# Production web build (served by the API from ./frontend in Docker)
build:
    cd web && bun run build

# Everything CI runs
check: lint test typecheck

lint:
    {{ venv }}/bin/ruff check backend
    {{ venv }}/bin/ruff format --check backend
    bun run lint

typecheck:
    bun run typecheck

test:
    {{ py }} -m pytest backend/tests -q

# Browser tests for the web UI. Needs the dev stack running (just dev); installs playwright on first run.
test-web:
    @{{ py }} -c 'import playwright' 2>/dev/null || (uv pip install -q -p {{ venv }} playwright && {{ py }} -m playwright install chromium)
    status=0; for t in web/tests/test_*.py; do echo "== $t"; {{ py }} "$t" || status=1; done; exit $status

# Fresh demo dataset for the web tests (no API keys needed).
seed-demo dir="data":
    {{ py }} -m backend.seed_demo --data-dir {{ dir }}

# Score frozen eval cases against the configured provider.
#   just eval --all | --copilot | --embedder stub
eval *ARGS:
    {{ py }} -m backend.eval.run_eval {{ ARGS }}

# CI gate: non-zero exit when precision/recall regress past threshold
eval-ci:
    {{ py }} -m backend.eval.run_eval --ci

# Deterministic fake provider: proves the scorer runs, says nothing about quality
eval-stub:
    {{ py }} -m backend.eval.run_eval --stub --all

# Delete meetings past their org's retention window (dry run without --commit)
purge *ARGS:
    {{ py }} -m backend.meetings.retention {{ ARGS }}

# Run the pipeline on one audio file from the command line
pipeline *ARGS:
    {{ py }} -m backend.run_pipeline {{ ARGS }}

# Print a fresh API key for MEETINGOS_API_KEY
gen-key:
    @{{ py }} -c "import secrets; print(secrets.token_urlsafe(32))"

db-reset:
    rm -f data/meetingos.db
    {{ py }} -c "from backend.database import init_db; init_db()"

# Regenerate the hashed lock file after changing backend/requirements.txt
lock:
    uv pip compile backend/requirements.txt --generate-hashes --python {{ py }} -o backend/requirements.lock.txt

# Lock installs cleanly and carries no known CVE
audit:
    uv pip install -q -p {{ venv }} pip-audit
    {{ venv }}/bin/pip-audit -r backend/requirements.lock.txt --progress-spinner off

docker:
    docker compose up --build
