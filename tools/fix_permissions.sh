#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-sessions/leclerc_profile}"

mkdir -p "${TARGET_DIR}"
sudo chown -R 1000:1000 "${TARGET_DIR}"
echo "Permissions updated for ${TARGET_DIR} (1000:1000)."
