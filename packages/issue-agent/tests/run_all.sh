#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
    set -a; source .env; set +a
fi

export PYTHONPATH="$ROOT/packages/evaluator/src:$ROOT/packages/issue-agent/src:$HERE"
VENV="$ROOT/packages/evaluator/.venv/bin/python3"

echo "=== Unit Tests ==="
$VENV -m unittest \
    "$HERE/test_schemas.py" \
    "$HERE/test_agent.py" \
    "$HERE/test_repository.py" \
    "$HERE/test_mapper.py" \
    -v