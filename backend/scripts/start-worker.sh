#!/usr/bin/env bash
# Start the arq worker for XProject.
#
# Runs in the foreground so crashes are immediately visible in the
# terminal that started it. Also tees stderr+stdout to a log file
# at /tmp/xproject-worker.log for after-the-fact debugging.
#
# Usage (from any directory):
#     ./scripts/start-worker.sh
#
# Sundance day-of: open a dedicated terminal tab, run this command,
# and DO NOT close that tab during the event. Any traceback will
# dump live in that terminal. The dashboard's "Polling stalled"
# badge is the visual backup signal that polling is alive.
#
# To stop: Ctrl-C in that terminal.

set -euo pipefail

cd "$(dirname "$0")/.."

# Activate venv if not already
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  source venv/bin/activate
fi

LOG=/tmp/xproject-worker.log
echo ""
echo "=================================================="
echo "  XProject arq worker starting"
echo "  Logs tee'd to: $LOG"
echo "  Press Ctrl-C to stop"
echo "=================================================="
echo ""

exec arq app.workers.scheduler.WorkerSettings 2>&1 | tee -a "$LOG"
