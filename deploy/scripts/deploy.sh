#!/usr/bin/env bash
# Production Deployment Script for Control Hub
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/deploy/docker-compose.prod.yml"
ENV_FILE="${ROOT_DIR}/deploy/env/.env.production"
BROADCAST_WORKER_REPLICAS="${BROADCAST_WORKER_REPLICAS:-10}"

echo "=========================================================="
echo "🚀 Starting Control Hub Production Deployment"
echo "=========================================================="

# 1. Environment file check
if [ ! -f "${ENV_FILE}" ]; then
    echo "❌ Error: Production environment file ${ENV_FILE} not found!"
    exit 1
fi

# 2. Database Backup before deployment
echo "📦 Step 1: Performing Pre-Deployment Database Backup..."
"${SCRIPT_DIR}/backup.sh" || {
    echo "⚠️ Warning: Pre-deployment backup failed. Prompting for safety..."
    read -p "Continue deployment anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment aborted by operator."
        exit 1
    fi
}

# 3. Pull & Build updated application images
echo "🔨 Step 2: Building Application Docker Images..."
docker compose -f "${COMPOSE_FILE}" build --no-cache

# 4. Ensure DB and Redis are up
echo "🔌 Step 3: Starting PostgreSQL and Redis..."
docker compose -f "${COMPOSE_FILE}" up -d postgres redis

echo "⏳ Waiting for database and redis healthchecks..."
docker compose -f "${COMPOSE_FILE}" exec postgres pg_isready -U postgres -d control_hub || sleep 5

# 5. Run Database Migrations
echo "🗄️ Step 4: Applying Database Migrations (alembic upgrade head)..."
"${SCRIPT_DIR}/migrate.sh" || {
    echo "❌ Database migration failed! Aborting deployment."
    exit 1
}

# 6. Start/Update Application, Workers, and Scheduler
echo "⚡ Step 5: Starting Application and Worker Services..."
echo "Broadcast worker replicas: ${BROADCAST_WORKER_REPLICAS}"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans \
    --scale worker-broadcast="${BROADCAST_WORKER_REPLICAS}" \
    app worker-telegram worker-video worker-broadcast worker-catchup worker-lifecycle scheduler

# 7. Health and Readiness Checks
echo "🏥 Step 6: Verifying Deployment Health & Readiness..."
sleep 5
"${SCRIPT_DIR}/healthcheck.sh" || {
    echo "❌ Health check failed post-deployment! Please review logs."
    echo "Run: docker compose -f ${COMPOSE_FILE} logs -f"
    exit 1
}

echo "=========================================================="
echo "✅ Control Hub Deployment Successfully Completed!"
echo "=========================================================="
