#!/usr/bin/env bash
# Database Migration Script for Control Hub
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/deploy/docker-compose.prod.yml"

echo "🗄️ Running Alembic Migrations: alembic upgrade head..."

docker compose -f "${COMPOSE_FILE}" run --rm migrate

echo "✅ Migrations applied successfully."
