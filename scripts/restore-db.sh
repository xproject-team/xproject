#!/usr/bin/env bash
# XProject DB restore script — Sundance disaster-recovery layer.
#
# Usage:
#   ./scripts/restore-db.sh <backup-file.sql>                  # restore to scratch DB
#   ./scripts/restore-db.sh <backup-file.sql> xproject_dev     # restore to specific DB
#
# DEFAULTS TO A SCRATCH DB (xproject_restore_test) to prevent accidental
# overwrite of the live dev DB. To restore over xproject_dev itself,
# explicitly pass it as the second argument AND confirm at the prompt.
#
# Restoration steps:
#   1. Drop the target DB if it exists
#   2. Recreate empty
#   3. Pipe the .sql file into psql
#   4. Report row counts on key tables to confirm restore worked

set -euo pipefail

BACKUP_FILE="${1:-}"
TARGET_DB="${2:-xproject_restore_test}"
DB_USER="${DB_USER:-mohammadhesam}"

if [[ -z "${BACKUP_FILE}" ]]; then
    echo "ERROR: backup file path required"
    echo "Usage: $0 <backup-file.sql> [target-db]"
    exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "ERROR: backup file not found: ${BACKUP_FILE}"
    exit 1
fi

echo "═══ XProject DB restore ═══"
echo "  Source:  ${BACKUP_FILE}"
echo "  Target:  ${TARGET_DB}"
echo "  User:    ${DB_USER}"
echo ""

# Safety: explicit confirmation when restoring over the live dev DB
if [[ "${TARGET_DB}" == "xproject_dev" ]]; then
    read -rp "⚠️  This OVERWRITES xproject_dev. Type 'YES' to confirm: " CONFIRM
    if [[ "${CONFIRM}" != "YES" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

START_TIME=$(date +%s)

# Drop and recreate the target DB
psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${TARGET_DB};" >/dev/null
psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${TARGET_DB};" >/dev/null

# Restore
psql -U "${DB_USER}" -d "${TARGET_DB}" < "${BACKUP_FILE}" >/dev/null

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "✅ Restore complete in ${ELAPSED}s"
echo ""
echo "═══ Row counts ═══"
psql -U "${DB_USER}" -d "${TARGET_DB}" -c "
SELECT 'tenants'             AS table, COUNT(*) AS rows FROM tenants
UNION ALL SELECT 'events',             COUNT(*) FROM events
UNION ALL SELECT 'bars',               COUNT(*) FROM bars
UNION ALL SELECT 'products',           COUNT(*) FROM products
UNION ALL SELECT 'bar_stock',          COUNT(*) FROM bar_stock
UNION ALL SELECT 'stock_transactions', COUNT(*) FROM stock_transactions
UNION ALL SELECT 'alerts',             COUNT(*) FROM alerts
UNION ALL SELECT 'users',              COUNT(*) FROM users
ORDER BY 1;
"
