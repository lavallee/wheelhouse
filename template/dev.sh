#!/usr/bin/env bash
# Run the admin locally in development mode (fixed local identity, no sign-in).
set -euo pipefail
cd "$(dirname "$0")"
test -s web/index.html || (cd ui && npm ci --no-audit --no-fund && npm run build)
SAMPLE_ADMIN_MODE=dev exec uv run uvicorn app:app --app-dir backend --host 127.0.0.1 --port "${PORT:-8870}" --timeout-graceful-shutdown 3
