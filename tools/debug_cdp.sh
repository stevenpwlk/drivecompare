#!/usr/bin/env bash
set -euo pipefail

LECLERC_CDP_URL=${LECLERC_CDP_URL:-http://leclerc-gui:9222}

echo "Testing CDP from worker at ${LECLERC_CDP_URL}..."
docker compose exec -T worker python - <<PY
import json
import os
import urllib.request

url = os.getenv("LECLERC_CDP_URL", "${LECLERC_CDP_URL}") + "/json/version"
with urllib.request.urlopen(url, timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
print(json.dumps(payload, indent=2, ensure_ascii=False))
PY
echo "OK"
