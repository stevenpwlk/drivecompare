#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== docker compose ps =="
docker compose ps || true
echo

echo "== leclerc-gui: ports/listeners (inside container) =="
docker compose exec -T leclerc-gui bash -lc 'ss -lntp | egrep "9222|3000|3001" || true'
echo

echo "== leclerc-gui: /json/version (inside container) =="
docker compose exec -T leclerc-gui bash -lc 'curl -fsS http://127.0.0.1:9222/json/version | head -c 200; echo' || true
echo

echo "== worker -> leclerc-gui CDP =="
docker compose exec -T worker sh -lc 'curl -fsS http://leclerc-gui:9222/json/version | head -c 200; echo' || true
echo

echo "== backend health =="
curl -fsS http://127.0.0.1:8000/health || true
echo

echo "== backend leclerc search =="
curl -fsS "http://127.0.0.1:8000/api/leclerc/search?q=test" | head -c 200
echo
