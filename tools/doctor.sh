#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== docker compose ps =="
docker compose ps || true
echo

echo "== leclerc-gui: listeners (inside container) =="
docker compose exec -T leclerc-gui bash -lc 'ss -lntp | egrep "9222|9223|3000|3001" || true'
echo

echo "== leclerc-gui: CDP local (9222) =="
docker compose exec -T leclerc-gui bash -lc 'curl -fsS http://127.0.0.1:9222/json/version | head -c 200; echo' || true
echo

echo "== leclerc-cdp: CDP proxy (9223) =="
docker compose exec -T leclerc-cdp sh -lc 'wget -qO- http://127.0.0.1:9223/json/version | head -c 200; echo' || true
echo

echo "== worker -> CDP local (9222) (same netns) =="
docker compose exec -T worker sh -lc 'curl -fsS http://127.0.0.1:9222/json/version | head -c 200; echo' || true
echo

echo "== backend health =="
curl -fsS http://127.0.0.1:8000/health || true
echo

echo "== backend -> worker ready (via leclerc-gui:9000) =="
docker compose exec -T backend sh -lc 'python -c "import urllib.request; print(urllib.request.urlopen(\"http://leclerc-gui:9000/ready\", timeout=3).read())"' || true
echo

echo "== backend leclerc search =="
curl -sv "http://127.0.0.1:8000/api/leclerc/search?q=test" | head -n 40 || true
echo
