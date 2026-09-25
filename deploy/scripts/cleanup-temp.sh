#!/usr/bin/env bash
# Temporary Thumbnail Cache Cleanup Script for Control Hub
set -euo pipefail

TEMP_DIR="${TEMP_DIR:-/tmp/controlhub}"

if [ -d "${TEMP_DIR}" ]; then
    echo "🧹 Cleaning up temporary thumbnail files older than 60 minutes in ${TEMP_DIR}..."
    find "${TEMP_DIR}" -type f -mmin +60 -exec rm -f {} +
    echo "✅ Temp directory cleanup completed."
else
    echo "ℹ️ Directory ${TEMP_DIR} does not exist. Nothing to clean."
fi
