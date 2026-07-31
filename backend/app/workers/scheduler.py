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
    cron_auto_transition_event_statuses,
    cron_close_paused_invoices,
    cron_evaluate_all_live_events,
    cron_generate_reports_for_completed_events,
    cron_poll_slesh_for_all_live_events,
    cron_refresh_customer_intelligence_for_all_live_events,
    cron_sync_bars_from_slesh,
    evaluate_alerts,
    generate_report,
    poll_slesh_for_event,
    populate_customer_features,
    refresh_customer_intelligence,
    retrain_demand_predictor,
    retrain_predictor,
    run_predictions,
)


class WorkerSettings:
    """arq worker configuration — registers functions and cron jobs."""

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Functions that can be enqueued on-demand by other code.
    functions = [
        run_predictions,
        retrain_predictor,
        retrain_demand_predictor,
        evaluate_alerts,
        generate_report,
        poll_slesh_for_event,
        populate_customer_features,
        refresh_customer_intelligence,
        cron_evaluate_all_live_events,
        cron_generate_reports_for_completed_events,
        cron_close_paused_invoices,
        cron_poll_slesh_for_all_live_events,
        cron_sync_bars_from_slesh,
        cron_auto_transition_event_statuses,
        cron_refresh_customer_intelligence_for_all_live_events,
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
        # Slesh POS polling. Every 60 seconds during a live event (Day 4,
        # Jul-19 sprint — tightened from the prior 2-minute cadence) so the
        # dashboard reflects sales within ~60s of them happening at the
        # bar. arq's cron minute= granularity is once-per-minute at best;
        # every-minute (all 60 values) is the fastest this scheduler can
        # go without a sub-minute polling mechanism. Collisions with other
        # crons are fine — arq enqueues independently and the 10 worker
        # slots run them in parallel.
        cron(
            cron_poll_slesh_for_all_live_events,
            minute=set(range(0, 60, 1)),
            run_at_startup=True,  # Fire on boot so a freshly-started worker catches up immediately
        ),
        # Bars sync from Slesh. Hourly cadence (minute=4, on the hour
        # only) is plenty — shop names + active state rarely change
        # mid-event. run_at_startup=True ensures a freshly-restarted
        # worker has the current Slesh shop list before any other work.
        # See: cron_sync_bars_from_slesh in tasks.py for behavior.
        cron(
            cron_sync_bars_from_slesh,
            hour=None,                       # every hour
            minute={4},                      # on minute 4 of the hour
            run_at_startup=True,
        ),
        # Event state machine auto-transitions. Every 5 min on offset
        # {4, 9, 14, ...} which only overlaps with the hourly bars sync
        # at :04 (acceptable — both short-running, read-mostly).
        # Three responsibilities per tick:
        #   1. DRAFT events past scheduled_at -> auto-activate + start
        #   2. ACTIVE events past scheduled_at -> auto-start
        #   3. LIVE events past scheduled_end_at AND silent 60 min ->
        #      auto-end
        # Safety net for Omar forgetting to click Start/End at Sundance.
        cron(
            cron_auto_transition_event_statuses,
            minute={4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59},
            run_at_startup=True,   # Fire on boot in case worker
                                   # restarts after a missed schedule.
        ),
        # Day 4 customer-intelligence panel. Every 5 min for LIVE events,
        # offset {3, 8, 13, ...} to avoid the alerts/reports/invoices/
        # bars-sync crons above. Proactively refreshes the ~30s cache and
        # WS-notifies connected dashboards even if nobody's actively
        # polling right then — same rationale as cron_evaluate_all_live_events.
        cron(
            cron_refresh_customer_intelligence_for_all_live_events,
            minute={3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58},
            run_at_startup=True,
        ),
    ]

    # Worker-level settings (arq defaults are fine; these are explicit for
    # clarity and future tuning).
    max_jobs = 10                  # Concurrent job slots per worker
    job_timeout = 60               # seconds — evaluations are ~1-3 sec each
    # Must stay BELOW the shortest cron interval. arq's enqueue_job()
    # returns None when a job's _job_id still has a result key, so a
    # keep_result longer than the poll cadence silently blocks every
    # subsequent enqueue. At 3600 with a 60s Slesh poll this produced
    # one poll per hour instead of one per minute — ingestion looked
    # "stalled" on the dashboard for the whole of Sundance 19 Jul until
    # the key was deleted by hand. Results are only read for log
    # counters, so a short window costs nothing.
    keep_result = 30               # seconds