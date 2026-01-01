#!/usr/bin/env bash
set -euo pipefail

LECLERC_CDP_URL=${LECLERC_CDP_URL:-http://localhost:9222}

echo "Testing CDP at ${LECLERC_CDP_URL}..."
curl -fsS "${LECLERC_CDP_URL}/json/version" | python -m json.tool
echo "OK"
