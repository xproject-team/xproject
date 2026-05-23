#!/usr/bin/env bash
# XProject — manual alert pipeline check.
#
# Runs AlertsOrchestrator.run_all() against the current LIVE event and
# reports what fires + what changes in the DB. Non-destructive.
#
# Use on event day if you suspect the cron worker is stuck — this proves
# the pipeline logic itself still works.
#
# Usage:
#   ./scripts/alert-pipeline-check.sh

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend"
cd "${BACKEND_DIR}"
source venv/bin/activate

# Discover the current LIVE event
TENANT_EVENT="$(psql xproject_dev -t -A -F '|' -c "
SELECT tenant_id, id FROM events WHERE status = 'LIVE' LIMIT 1;
")"

if [[ -z "${TENANT_EVENT}" ]]; then
    echo "⚠️  No LIVE event found. Nothing to evaluate."
    exit 1
fi

TENANT_ID="${TENANT_EVENT%|*}"
EVENT_ID="${TENANT_EVENT#*|}"

echo "═══ Alert pipeline check ═══"
echo "  Tenant:  ${TENANT_ID}"
echo "  Event:   ${EVENT_ID}"
echo ""

python3 << PYEOF
import sys; sys.path.insert(0, '.')
import asyncio, uuid
import app.main
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.modules.alerts.engine import AlertsOrchestrator

TENANT_ID = uuid.UUID("${TENANT_ID}")
EVENT_ID  = uuid.UUID("${EVENT_ID}")

STATE_SQL = """
SELECT
  CASE
    WHEN auto_resolved_at IS NOT NULL THEN 'resolved'
    WHEN expired_at IS NOT NULL       THEN 'expired'
    WHEN acknowledged_at IS NOT NULL  THEN 'acknowledged'
    ELSE 'active'
  END AS state,
  COUNT(*) AS n
FROM alerts WHERE event_id = :eid
GROUP BY 1 ORDER BY 1
"""

async def run():
    async with AsyncSessionLocal() as session:
        before = (await session.execute(text(STATE_SQL), {"eid": EVENT_ID})).all()
        print("BEFORE:")
        for s, n in before:
            print(f"  {s:15} {n}")
        print()

        totals = await AlertsOrchestrator(session).run_all(TENANT_ID, EVENT_ID)
        await session.commit()
        print(f"Orchestrator returned: {totals}")
        print()

        after = (await session.execute(text(STATE_SQL), {"eid": EVENT_ID})).all()
        print("AFTER:")
        for s, n in after:
            print(f"  {s:15} {n}")

asyncio.run(run())
PYEOF
