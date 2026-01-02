#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}

echo "Status:"
curl -fsS "${BACKEND_URL}/leclerc/unblock/status" | python -m json.tool
echo

echo "Mark done without body:"
curl -fsS -X POST "${BACKEND_URL}/leclerc/unblock/done" | python -m json.tool
echo
