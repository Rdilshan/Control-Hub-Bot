#!/usr/bin/env bash
# Production Healthcheck Script for Control Hub
set -euo pipefail

APP_URL="${APP_URL:-http://localhost:8000}"

echo "🏥 Checking Application Liveness (/health)..."
HEALTH_STATUS=$(curl -fsS "${APP_URL}/health" 2>/dev/null || echo "FAILED")
if [[ "${HEALTH_STATUS}" =~ "status" ]]; then
    echo "  ✅ Liveness Check: OK (${HEALTH_STATUS})"
else
    echo "  ❌ Liveness Check: FAILED"
    exit 1
fi

echo "🏥 Checking Application Readiness (/ready)..."
READY_STATUS=$(curl -fsS "${APP_URL}/ready" 2>/dev/null || echo "FAILED")
if [[ "${READY_STATUS}" =~ "ready" ]]; then
    echo "  ✅ Readiness Check: OK (${READY_STATUS})"
else
    echo "  ❌ Readiness Check: FAILED (${READY_STATUS})"
    exit 1
fi

echo "✅ All health and readiness checks passed."
