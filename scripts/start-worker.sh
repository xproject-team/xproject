#!/usr/bin/env bash
#
# Start the arq worker for XProject.
#
# Runs the scheduler defined in backend/app/workers/scheduler.py.
# Cron jobs registered there handle:
#   - polling Slesh POS every cycle for live events
#   - evaluating alerts (depletion / demand-spike / recipe-deviation)
#   - generating reports for completed events
#   - closing paused invoices
#
# Pre-flight checks before starting:
#   1. backend/venv exists
#   2. arq is installed in the venv
#   3. Redis is reachable on the configured URL
#
# Usage from repo root:
#   ./scripts/start-worker.sh
#
# Exits with code 1 and a clear message if any check fails.
# Starts arq in the foreground so logs are visible.  Stop with Ctrl+C.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
VENV_BIN="${BACKEND_DIR}/venv/bin"

echo "==> XProject arq worker bootstrap"
echo "    repo:    ${REPO_ROOT}"
echo "    backend: ${BACKEND_DIR}"

# ── 1. Venv ─────────────────────────────────────────────────────────────────
if [[ ! -d "${VENV_BIN}" ]]; then
  echo "ERROR: backend venv not found at ${VENV_BIN}" >&2
  echo "       Set up the backend first: cd backend && python3 -m venv venv && pip install -r requirements.txt" >&2
  exit 1
fi

# ── 2. arq installed ────────────────────────────────────────────────────────
if [[ ! -x "${VENV_BIN}/arq" ]]; then
  echo "ERROR: arq binary not found at ${VENV_BIN}/arq" >&2
  echo "       Install with: source backend/venv/bin/activate && pip install -r backend/requirements.txt" >&2
  exit 1
fi

# ── 3. Redis ping ───────────────────────────────────────────────────────────
# Pull REDIS_URL from .env if present, otherwise default
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
if [[ -f "${REPO_ROOT}/.env" ]]; then
  RU="$(grep -E '^REDIS_URL=' "${REPO_ROOT}/.env" | tail -1 | cut -d= -f2- || true)"
  if [[ -n "${RU}" ]]; then
    REDIS_URL="${RU}"
  fi
fi

echo "    redis:   ${REDIS_URL}"

# Use the venv's python to ping Redis — avoids requiring redis-cli on the host
"${VENV_BIN}/python" - <<PYCHECK
import sys
try:
    import redis  # arq depends on this
except ImportError:
    sys.stderr.write('ERROR: redis-py not installed (should be a transitive dep of arq)\n')
    sys.exit(2)

try:
    r = redis.Redis.from_url('${REDIS_URL}')
    pong = r.ping()
    if not pong:
        sys.stderr.write('ERROR: Redis ping returned falsy at ${REDIS_URL}\n')
        sys.exit(3)
except Exception as exc:
    sys.stderr.write(f'ERROR: Redis unreachable at ${REDIS_URL}: {exc}\n')
    sys.stderr.write('       Start Redis: docker start redis  (or check your Redis container)\n')
    sys.exit(4)
PYCHECK

echo "    arq:     ${VENV_BIN}/arq"
echo "==> All pre-flight checks passed. Starting worker (Ctrl+C to stop)"
echo

cd "${BACKEND_DIR}"
exec "${VENV_BIN}/arq" app.workers.scheduler.WorkerSettings
