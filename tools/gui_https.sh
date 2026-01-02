#!/usr/bin/env bash
set -euo pipefail

GUI_HTTPS_URL=${GUI_HTTPS_URL:-https://localhost:5801}

echo "Testing GUI HTTPS at ${GUI_HTTPS_URL}..."
curl -kfsS "${GUI_HTTPS_URL}" >/dev/null
echo "OK"
