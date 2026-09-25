#!/usr/bin/env bash
# Database Restore Script for Control Hub
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/deploy/docker-compose.prod.yml"

BACKUP_FILE="${1:-}"

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "Usage: $0 <path-to-backup.sql.gz>"
    echo "Example: $0 ${ROOT_DIR}/backups/control_hub_db_20260925_000000.sql.gz"
    exit 1
fi

echo "=========================================================="
echo "⚠️  DATABASE RESTORE INITIATED"
echo "Target Backup: ${BACKUP_FILE}"
echo "=========================================================="

# Checksum verification if available
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [ -f "${CHECKSUM_FILE}" ]; then
    echo "🔍 Verifying SHA256 checksum..."
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -c "${CHECKSUM_FILE}" || {
            echo "❌ Checksum verification failed!"
            exit 1
        }
    fi
    echo "✅ Checksum verified."
fi

# Operator confirmation
read -p "🚨 WARNING: This will overwrite the current database! Are you sure? (type 'RESTORE'): " CONFIRM
if [ "${CONFIRM}" != "RESTORE" ]; then
    echo "Restore aborted by operator."
    exit 1
fi

echo "🛑 Stopping application and workers to prevent concurrent writes..."
docker compose -f "${COMPOSE_FILE}" stop app worker-telegram worker-video worker-broadcast worker-catchup worker-lifecycle scheduler

echo "🗄️ Restoring database from backup..."
gunzip -c "${BACKUP_FILE}" | docker compose -f "${COMPOSE_FILE}" exec -T postgres psql -U postgres -d control_hub

echo "⚡ Restarting application and workers..."
docker compose -f "${COMPOSE_FILE}" start app worker-telegram worker-video worker-broadcast worker-catchup worker-lifecycle scheduler

echo "🏥 Verifying database health..."
sleep 3
"${SCRIPT_DIR}/healthcheck.sh"

echo "=========================================================="
echo "✅ Database Restore Completed Successfully!"
echo "=========================================================="
