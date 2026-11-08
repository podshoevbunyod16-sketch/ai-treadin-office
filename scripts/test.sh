#!/usr/bin/env bash
# Run all automated tests (backend + frontend) and the production build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements-dev.txt
.venv/bin/python -m pytest -q
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
npm test
npm run build
