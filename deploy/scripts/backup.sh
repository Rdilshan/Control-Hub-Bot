#!/usr/bin/env bash
# Automated PostgreSQL Backup Script for Control Hub
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/control_hub_db_${TIMESTAMP}.sql.gz"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"
COMPOSE_FILE="${ROOT_DIR}/deploy/docker-compose.prod.yml"

mkdir -p "${BACKUP_DIR}"

echo "📦 Initiating Database Backup to ${BACKUP_FILE}..."

# Execute pg_dump from PostgreSQL container and compress
docker compose -f "${COMPOSE_FILE}" exec -T postgres pg_dump -U postgres -d control_hub --clean --if-exists | gzip > "${BACKUP_FILE}"

# Generate SHA256 Checksum
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
fi

BACKUP_SIZE="$(ls -lh "${BACKUP_FILE}" | awk '{print $5}')"
echo "✅ Backup completed: ${BACKUP_FILE} (Size: ${BACKUP_SIZE})"

# Retention Policy: Keep last 7 daily backups
echo "🧹 Applying retention policy (keeping last 7 daily backups)..."
find "${BACKUP_DIR}" -name "control_hub_db_*.sql.gz*" -type f -mtime +7 -exec rm -f {} +

echo "✅ Backup process finished."
