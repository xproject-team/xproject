#!/usr/bin/env bash
# XProject DB backup script — Sundance disaster-recovery layer.
#
# Usage:
#   ./scripts/backup-db.sh                  # full backup, default tag
#   ./scripts/backup-db.sh pre-deploy       # full backup, custom tag
#
# Writes a single .sql file to ./backups/ with the pattern:
#   xproject_dev_<tag>_<YYYYMMDD_HHMMSS>.sql
#
# Designed to be idempotent and safe to run during a live event.
# Uses pg_dump --no-owner --no-acl so the dump can be restored to any
# Postgres instance (e.g. a clean staging DB) without permission errors.

set -euo pipefail

DB_NAME="${DB_NAME:-xproject_dev}"
DB_USER="${DB_USER:-mohammadhesam}"
BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backups"
TAG="${1:-snapshot}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT="${BACKUP_DIR}/${DB_NAME}_${TAG}_${TIMESTAMP}.sql"

mkdir -p "${BACKUP_DIR}"

echo "═══ XProject DB backup ═══"
echo "  DB:      ${DB_NAME}"
echo "  User:    ${DB_USER}"
echo "  Tag:     ${TAG}"
echo "  Output:  ${OUTPUT}"
echo ""

START_TIME=$(date +%s)
pg_dump --no-owner --no-acl -U "${DB_USER}" "${DB_NAME}" > "${OUTPUT}"
END_TIME=$(date +%s)

SIZE_KB=$(du -k "${OUTPUT}" | awk '{print $1}')
ELAPSED=$((END_TIME - START_TIME))

echo "✅ Backup complete"
echo "   Size:    ${SIZE_KB} KB"
echo "   Elapsed: ${ELAPSED}s"
echo ""
echo "Restore command:"
echo "   ./scripts/restore-db.sh ${OUTPUT}"
