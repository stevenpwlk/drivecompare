#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}

echo "Status:"
curl -fsS "${BACKEND_URL}/api/unblock/state" | python -m json.tool
echo

echo "Reset unblock state:"
curl -fsS -X POST "${BACKEND_URL}/api/unblock/reset" | python -m json.tool
echo
