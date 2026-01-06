#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://127.0.0.1:8000}

echo "Checking backend health..."
curl -fsS "${BACKEND_URL}/health" >/dev/null

echo "Checking UI..."
curl -fsS "${BACKEND_URL}/" >/dev/null

echo "Checking worker readiness (via backend)..."
ready="$(curl -sS --max-time 20 "${BACKEND_URL}/api/worker/ready" || true)"
echo "${ready}"
echo "${ready}" | grep -Eq '"ok"\s*:\s*true' || { echo "Worker not ready"; exit 1; }

echo "Running Leclerc search..."
curl -sS --max-time 240 "${BACKEND_URL}/api/leclerc/search?q=coca&limit=10"
echo
