#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL=${BACKEND_URL:-http://localhost:8000}
WORKER_URL=${WORKER_URL:-http://localhost:9000}
GUI_HTTPS_URL=${GUI_HTTPS_URL:-https://localhost:5801}

echo "Checking backend health..."
curl -fsS "${BACKEND_URL}/health" >/dev/null

echo "Checking UI..."
curl -fsS "${BACKEND_URL}/" >/dev/null

echo "Checking worker readiness..."
curl -fsS "${WORKER_URL}/ready" >/dev/null

echo "Checking GUI HTTPS..."
curl -kfsS "${GUI_HTTPS_URL}" >/dev/null

echo "Checking CDP from worker..."
docker compose exec -T worker python - <<'PY'
import json
import os
import urllib.request

url = os.getenv("LECLERC_CDP_URL", "http://127.0.0.1:9222") + "/json/version"
with urllib.request.urlopen(url, timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
print("CDP OK:", payload.get("Browser"))
PY

cleanup() {
  docker compose up -d leclerc-gui >/dev/null
}

trap cleanup EXIT

echo "Stopping leclerc-gui to simulate CDP down..."
docker compose stop leclerc-gui >/dev/null

echo "Creating job (expect FAILED when CDP is down)..."
JOB_ID=$(curl -fsS -X POST "${BACKEND_URL}/jobs/leclerc-search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"coca"}' | python -c 'import sys, json; print(json.load(sys.stdin)["job_id"])')
echo "Job created: ${JOB_ID}"

status=""
error=""
for _ in {1..30}; do
  payload=$(curl -fsS "${BACKEND_URL}/jobs/${JOB_ID}")
  status=$(python - <<'PY' <<<"${payload}"
import json, sys
data = json.load(sys.stdin)
print(data.get("status") or "")
PY
)
  error=$(python - <<'PY' <<<"${payload}"
import json, sys
data = json.load(sys.stdin)
print(data.get("error") or "")
PY
)
  if [[ "${status}" == "FAILED" ]]; then
    break
  fi
  sleep 1
done

if [[ "${status}" != "FAILED" ]]; then
  echo "Job did not reach FAILED status (last status: ${status})" >&2
  exit 1
fi

if [[ -z "${error}" ]]; then
  echo "Job failed without error message" >&2
  exit 1
fi

if [[ ! "${error}" =~ (CDP|cdp|connect|ECONNREFUSED) ]]; then
  echo "Job error does not mention CDP/connectivity: ${error}" >&2
  exit 1
fi

echo "Job failed as expected: ${error}"
echo "Smoke test complete."
