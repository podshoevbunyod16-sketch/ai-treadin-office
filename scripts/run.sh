#!/usr/bin/env bash
# Build the frontend and start the backend (serves UI + API + WebSocket on one port).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
npm run build

cd "$ROOT/backend"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" --proxy-headers
