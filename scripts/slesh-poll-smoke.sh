#!/bin/bash
# slesh-poll-smoke.sh
#
# Pre-Sundance pre-flight smoke test for the Slesh order-polling pipeline.
#
# Runs one polling cycle on demand against the live Sundance 2026 event
# and reports pass/fail in plain language. Wraps the existing manual
# trigger at app.scripts.poll_slesh_orders.
#
# Exit codes:
#   0 — green, polling stack is healthy
#   1 — red, polling stack has a problem; investigate
#
# Usage:
#   ./scripts/slesh-poll-smoke.sh
#
# On Sundance day, run this:
#   - before the event (T-2 hours): expect orders_seen=0, status=ok
#   - 10 min into the event:        expect orders_seen>0, status=ok
#   - any time it returns non-zero: STOP and investigate

set -euo pipefail

# ─── Config (matches the live Sundance 2026 event) ──────────────────────
TENANT_SLUG="noma-group"
EVENT_ID="e7866455-b721-419e-8d10-e5e157ff50d6"

# ─── Locate repo and venv ───────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
VENV="$BACKEND/venv"

if [[ ! -d "$VENV" ]]; then
    echo "❌ venv not found at $VENV"
    echo "   Run: cd $BACKEND && python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

# ─── Snapshot pre-state ─────────────────────────────────────────────────
PRE_COUNT=$(psql xproject_dev -t -A -c \
  "SELECT COUNT(*) FROM stock_transactions WHERE event_id = '$EVENT_ID';")

echo "═══ Slesh polling smoke test ═══"
echo "  tenant:           $TENANT_SLUG"
echo "  event:            $EVENT_ID"
echo "  stock_tx before:  $PRE_COUNT"
echo ""
echo "─── Running one polling cycle ───"

# ─── Run the cycle ──────────────────────────────────────────────────────
cd "$BACKEND"
source "$VENV/bin/activate"

# Capture output for inspection AND show progress to stdout
TMP_LOG=$(mktemp)
trap 'rm -f "$TMP_LOG"' EXIT

START_NS=$(python3 -c 'import time; print(int(time.time_ns()))')

if python -m app.scripts.poll_slesh_orders \
    --tenant-slug "$TENANT_SLUG" \
    --event-id "$EVENT_ID" 2>&1 | tee "$TMP_LOG"; then
    POLL_RC=0
else
    POLL_RC=$?
fi

END_NS=$(python3 -c 'import time; print(int(time.time_ns()))')
DURATION_MS=$(( (END_NS - START_NS) / 1000000 ))

# ─── Snapshot post-state ────────────────────────────────────────────────
POST_COUNT=$(psql xproject_dev -t -A -c \
  "SELECT COUNT(*) FROM stock_transactions WHERE event_id = '$EVENT_ID';")
INGESTED=$(( POST_COUNT - PRE_COUNT ))

echo ""
echo "─── Verdict ───"
echo "  duration:         ${DURATION_MS}ms"
echo "  poll exit code:   $POLL_RC"
echo "  stock_tx after:   $POST_COUNT"
echo "  newly ingested:   $INGESTED"

# Extract structured status line from script output (it prints
# 'status=ok orders_seen=N orders_ingested=N ...')
STATUS_LINE=$(grep -oE 'status=[a-z_]+ orders_seen=[0-9]+ orders_ingested=[0-9]+' "$TMP_LOG" | tail -1 || echo "")

if [[ -z "$STATUS_LINE" ]]; then
    echo ""
    echo "❌ FAIL — could not parse status line from poll output"
    echo "   Check the full output above for errors."
    exit 1
fi

echo "  parsed:           $STATUS_LINE"

# ─── Pass/fail logic ────────────────────────────────────────────────────
# Healthy signals:
#   1. Exit code 0
#   2. status=ok (NOT error / partial)
#   3. Newly-ingested DB rows >= reported orders_ingested
if [[ $POLL_RC -ne 0 ]]; then
    echo ""
    echo "❌ FAIL — poll exited non-zero ($POLL_RC)"
    exit 1
fi

if ! echo "$STATUS_LINE" | grep -q "status=ok"; then
    echo ""
    echo "❌ FAIL — poll status is not 'ok'"
    exit 1
fi

echo ""
echo "✅ PASS — Slesh polling stack is healthy"
echo "   Polling completed in ${DURATION_MS}ms with status=ok."
if [[ $INGESTED -gt 0 ]]; then
    echo "   Ingested $INGESTED new stock transactions during this cycle."
else
    echo "   No new orders to ingest (expected outside event hours)."
fi
exit 0
