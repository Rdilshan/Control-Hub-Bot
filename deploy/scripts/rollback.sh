#!/usr/bin/env bash
# Production Rollback Script for Control Hub
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/deploy/docker-compose.prod.yml"

echo "=========================================================="
echo "⏪ Initiating Control Hub Production Rollback"
echo "=========================================================="

TAG="${1:-}"

if [ -z "${TAG}" ]; then
    echo "Usage: $0 <target-git-tag-or-commit>"
    echo "Example: $0 v1.0.0"
    exit 1
fi

echo "📍 Target Rollback Tag: ${TAG}"

# 1. Checkout target version
echo "🔄 Checking out git ref: ${TAG}..."
git checkout "${TAG}"

# 2. Rebuild container images for previous tag
echo "🔨 Rebuilding containers for rollback target..."
docker compose -f "${COMPOSE_FILE}" build

# 3. Restart application and workers
echo "⚡ Restarting application services..."
docker compose -f "${COMPOSE_FILE}" up -d --force-recreate app worker-telegram worker-video worker-broadcast worker-catchup worker-lifecycle scheduler

# 4. Verify health
echo "🏥 Running post-rollback health checks..."
sleep 5
"${SCRIPT_DIR}/healthcheck.sh"

echo "=========================================================="
echo "✅ Rollback to ${TAG} completed successfully!"
echo "=========================================================="
