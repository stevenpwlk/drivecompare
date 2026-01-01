#!/usr/bin/env bash
set -euo pipefail

CERT_DIR=/certs
CERT_FILE=${CERT_DIR}/novnc.pem
KEY_FILE=${CERT_DIR}/novnc.key
DISPLAY_NUM=${DISPLAY:-:99}
START_URL=${LECLERC_START_URL:-https://www.e.leclerc/}
PROFILE_DIR=/sessions/leclerc-profile

mkdir -p "${CERT_DIR}" "${PROFILE_DIR}"

if [[ ! -f "${CERT_FILE}" || ! -f "${KEY_FILE}" ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "${KEY_FILE}" \
    -out "${CERT_FILE}" \
    -days 365 \
    -subj "/CN=drivecompare-local"
fi

Xvfb "${DISPLAY_NUM}" -screen 0 1920x1080x24 &
openbox &

CHROMIUM_BIN=$(python - <<'PY'
import glob
paths = glob.glob('/ms-playwright/chromium-*/chrome-linux/chrome')
print(paths[0] if paths else '')
PY
)
if [[ -z "${CHROMIUM_BIN}" ]]; then
  echo "Chromium binary not found" >&2
  exit 1
fi

"${CHROMIUM_BIN}" \
  --no-sandbox \
  --disable-dev-shm-usage \
  --remote-debugging-address=0.0.0.0 \
  --remote-debugging-port=9222 \
  --user-data-dir="${PROFILE_DIR}" \
  --no-first-run \
  --no-default-browser-check \
  --disable-features=TranslateUI \
  --start-maximized \
  "${START_URL}" &

x11vnc -display "${DISPLAY_NUM}" -forever -shared -nopw -rfbport 5900 &

NOVNC_PROXY=/usr/share/novnc/utils/novnc_proxy
if [[ ! -x "${NOVNC_PROXY}" ]]; then
  NOVNC_PROXY=/usr/share/novnc/utils/novnc_proxy.py
fi

"${NOVNC_PROXY}" --vnc localhost:5900 --listen 5801 --cert "${CERT_FILE}" --key "${KEY_FILE}" &

wait -n
