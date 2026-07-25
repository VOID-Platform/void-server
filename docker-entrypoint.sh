#!/bin/sh
set -e

SERVICE="${SERVICE:-api}"

export PYTHONPATH="/app/packages/evaluator/src:/app/packages/issue-agent/src"

case "$SERVICE" in
  api)
    echo "[entrypoint] 🚀 Synchronizing Prisma database schema..."
    npx prisma db push --skip-generate || true
    exec node apps/node-api/dist/index.js
    ;;
  worker)
    exec node apps/node-api/dist/worker.js
    ;;
  sampling-consumer)
    exec node apps/node-api/dist/sampling-consumer.js
    ;;
  *)
    echo "Unknown SERVICE: $SERVICE (expected: api, worker, sampling-consumer)"
    exit 1
    ;;
esac
