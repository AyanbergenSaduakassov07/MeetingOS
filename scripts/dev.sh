#!/usr/bin/env sh
# `npm run dev` (your data in ./data) or `npm run demo` (seeded demo in ./data/demo).
# Starts the API on :8470 and the web UI, opens the browser; Ctrl-C stops both.
set -eu
cd "$(dirname "$0")/.."

[ -x .venv/bin/python ] || { echo "No Python env yet. Run: just setup"; exit 1; }
[ -d node_modules ] || [ -d web/node_modules ] || { echo "No JS deps yet. Run: bun install"; exit 1; }

data=data
if [ "${1:-}" = demo ]; then
  data=data/demo
  [ -f "$data/meetingos.db" ] || .venv/bin/python -m backend.seed_demo --data-dir "$data"
fi

.venv/bin/python -m backend.main --data-dir "$data" &
api=$!
trap 'kill $api 2>/dev/null' EXIT INT TERM

cd web && npm run dev -- --open
