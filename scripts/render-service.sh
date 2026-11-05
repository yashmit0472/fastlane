#!/bin/bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL connection URL}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export FASTLANE_WORKER_MODEL_CHECK="${RENDER_GIT_COMMIT:-$(date +%s)}"

python -c 'from apps.api.database import initialize; initialize()'

python -m uvicorn apps.api.main:app --host 0.0.0.0 --port "${PORT:-10000}" &
api_pid=$!
python -m ml.live.refresh --loop --archive-limit 0 &
worker_pid=$!

cleanup() {
    kill "$api_pid" "$worker_pid" 2>/dev/null || true
    wait "$api_pid" "$worker_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT

wait -n "$api_pid" "$worker_pid"
exit 1
