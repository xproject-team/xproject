"""arq worker settings and scheduled job configuration.

Start the worker (in a separate terminal):

    cd ~/Projects/xproject/backend
    arq app.workers.scheduler.WorkerSettings

What this worker does:

1. Every 5 minutes the cron entry point `cron_evaluate_all_live_events`
   fires. It enumerates every event currently in status='live' across all
   tenants and enqueues one `evaluate_alerts` job per event.

2. Worker slots pull jobs from the Redis queue and run them. Each job is
   independent: a failure in one event's evaluation never blocks another.

3. The `evaluate_alerts` task uses our DepletionEvaluator, which consumes
   the burn-rate engine and fires / dedup-updates / auto-resolves alerts
   via AlertsService.

Reliability notes:
- Task bodies catch their own exceptions and return structured results;
  arq never sees a raised exception, so there are no infinite retry loops.
- Redis is required. The redis_url comes from settings (same Redis that
  powers chat pub/sub).
- `_job_id` dedup on cron-enqueued jobs means a slow tick followed by a
  fast tick won't double-schedule the same event's evaluation.
"""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.tasks import (
    cron_close_paused_invoices,
    cron_evaluate_all_live_events,
    cron_generate_reports_for_completed_events,
    evaluate_alerts,
    generate_report,
    run_predictions,
)


class WorkerSettings:
    """arq worker configuration — registers functions and cron jobs."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Functions that can be enqueued on-demand by other code.
    functions = [
        run_predictions,
        evaluate_alerts,
        generate_report,
        cron_evaluate_all_live_events,
        cron_generate_reports_for_completed_events,
        cron_close_paused_invoices,
    ]

    # Cron jobs run on a fixed schedule inside the worker process.
    # Every 5 minutes, enumerate live events and enqueue evaluations.
    cron_jobs = [
        cron(
            cron_evaluate_all_live_events,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=True,  # Fire once on worker start for fast demo
        ),
        # Post-event report generator runs on off-minutes so it doesn't
        # collide with the alerts evaluator. Every 5 min it scans for
        # events where ended_at < now - 15min AND no report exists, then
        # enqueues a generate_report job per eligible event.
        cron(
            cron_generate_reports_for_completed_events,
            minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56},
            run_at_startup=True,  # Fire on boot so recent events get picked up
        ),
        # 48h auto-close for warehouse invoices in PAUSED state. Per
        # docs/warehouse-module-spec.md §5, paused sessions older than 48h
        # auto-transition to DISCREPANCY so abandoned scans never linger.
        # Runs on yet-another off-minute offset {2, 7, 12, ...} to avoid
        # the other crons.
        cron(
            cron_close_paused_invoices,
            minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57},
            run_at_startup=False,  # No need to fire on boot — 48h cutoff is slow
        ),
    ]

    # Worker-level settings (arq defaults are fine; these are explicit for
    # clarity and future tuning).
    max_jobs = 10                  # Concurrent job slots per worker
    job_timeout = 60               # seconds — evaluations are ~1-3 sec each
    keep_result = 3600             # Keep job results in Redis for 1h