#!/usr/bin/env bash
# Local CI for wheelhouse: the package, the template, the registry manifest,
# and the hygiene check that keeps private names and local paths out.
set -euo pipefail
cd "$(dirname "$0")"
(cd python && uv sync --extra dev && uv run pytest -q)
(cd template && ./ci.sh)
(cd template/ui && npx shadcn registry validate && npx shadcn build -o ../../registry/r)
(cd python && uv run wheelhouse drift ../template/ui | tail -1 | grep -q " 0 differ, 0 missing")
python3 scripts/hygiene.py   # after the registry build, so the built files are checked too
echo "wheelhouse ci: pass"
