#!/usr/bin/env bash
# Local CI: everything a merge needs, from a clean checkout.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --extra dev
uv run pytest -q
(cd ui && npm ci --no-audit --no-fund && npm run build)
test -s web/index.html
echo "ci: pass"
