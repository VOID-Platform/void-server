#!/usr/bin/env bash
# Evaluate all incidents in the dataset against the live Gemini API.
# Usage:  ./evaluation_dataset/run_all.sh
set -euo pipefail

EVAL_DIR="evaluation_dataset/incidents"
PYTHON="packages/evaluator/.venv/bin/python3"
EVALUATOR="packages/evaluator/src"

if [ -z "${GOOGLE_API_KEY:-}" ]; then
    if [ -f ".env" ] && grep -q '^GOOGLE_API_KEY=' .env; then
        echo "Loading GOOGLE_API_KEY from .env"
        export GOOGLE_API_KEY=$(grep '^GOOGLE_API_KEY=' .env | head -1 | cut -d= -f2 | tr -d '"' | tr -d "'")
    else
        echo "ERROR: GOOGLE_API_KEY is not set." >&2
        echo "  Set it in .env or:  export GOOGLE_API_KEY='your-key-here'" >&2
        exit 1
    fi
fi

for incident_dir in "$EVAL_DIR"/*/; do
    name=$(basename "$incident_dir")
    echo "━━━ $name ━━━"
    PYTHONPATH="$EVALUATOR" "$PYTHON" -m evaluator < "$incident_dir/incident.json" 2>&1 || true
    echo
done
