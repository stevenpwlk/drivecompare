#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}

curl -fsS "${BACKEND_URL}/leclerc/unblock/status" | python -m json.tool
