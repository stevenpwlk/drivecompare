#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}
WORKER_URL=${WORKER_URL:-http://localhost:9000}
GUI_HTTPS_URL=${GUI_HTTPS_URL:-https://localhost:5801}

 echo "Checking backend health..."
 curl -fsS "${BACKEND_URL}/health" >/dev/null

 echo "Checking worker readiness..."
 curl -fsS "${WORKER_URL}/ready" >/dev/null

echo "Checking GUI HTTPS..."
curl -kfsS "${GUI_HTTPS_URL}" >/dev/null

 echo "Checking CDP from worker..."
 docker compose exec -T worker python - <<'PY'
import json
import os
import urllib.request

url = os.getenv("LECLERC_CDP_URL", "http://leclerc-gui:9222") + "/json/version"
with urllib.request.urlopen(url, timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
print("CDP OK:", payload.get("Browser"))
PY

 echo "Creating job..."
 JOB_ID=$(curl -fsS -X POST "${BACKEND_URL}/jobs/leclerc-search" \
   -H 'Content-Type: application/json' \
   -d '{"query":"coca"}' | python -c 'import sys, json; print(json.load(sys.stdin)["job_id"])')
 echo "Job created: ${JOB_ID}"
 echo "Smoke test complete."
