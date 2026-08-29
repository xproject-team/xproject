# Background-job status semantics — the silent-'ok' finding

Recorded 2026-08-29 so it outlives the week that found it. **In this
codebase, a worker job's `status: ok` means "the function did not
crash" — it does NOT mean the job accomplished anything.** Two live
demonstrations forced the point:

1. **Ingestion** (staging, Day 4→5): `poll_slesh_for_event` saw 9
   orders, ingested 0, reported `ok` — every line had failed with
   `BarNotInEventError`. On production this shape would mean revenue
   silently frozen while every status line stays green, because the
   success path also resets `consecutive_failures`, keeping the
   dashboard's polling-health pill healthy.
2. **Post-event pipeline** (staging, Day 5): closing an event with
   8,084 orders ran `populate_customer_features` in 1.92s — 0 sessions,
   0 purchases created, `status: ok`. Its sanity gate is vacuously true
   on the only path that runs automatically (`expected_customers=None`).

Job results additionally expire from Redis after `keep_result=30`
seconds (deliberately short — a longer value once silently throttled
polling to hourly; see scheduler.py), so even honest statuses are
unobservable minutes later. The worker log line is the only trace.

## Operator-verified census (29 Aug, against the full job registry)

**9 of 22 jobs return a fixed 'ok' regardless of outcome; 4 of them are
dangerous.** That census, verified by the operator against the running
system, is the authoritative headline. The per-function detail below is
the agent's audit of `app/workers/tasks.py` (15 task functions) that
fed it.

### Dangerous — 'ok' can mask total failure of the job's purpose

| Job | Why dangerous |
|---|---|
| `poll_slesh_for_event` | Passes through `PollResult.status`, which is transport-only: per-line ingestion failures are counted, logged, durably written to `ingestion_line_errors` (a table nothing reads) — and then `record_success` advances the cursor past the failed orders and resets the failure counter. Demonstration 1. |
| `populate_customer_features` | `"ok" if report.sanity_passed` — but the gate is `True` whenever `expected_customers is None`, which is always, on the automatic path. Demonstration 2. |
| `generate_report` | Returns `ok, reports_generated=N` where N counts whatever `generate_for_event_batch` returned — that method swallows per-language failures, so both languages failing yields `ok, reports_generated: 0`. |
| `run_predictions` | A stub: literally hardcoded `{"status": "ok", "predictions_generated": 0}` on every call. |

### Status-blind but counter-carrying — 'ok' fixed, failures visible only inside the payload

`cron_sync_bars_from_slesh` (carries an `errors` count that never
touches status), `cron_close_paused_invoices` (`failed` count, same),
`cron_auto_transition_event_statuses` (`errors` count, same),
`evaluate_alerts` and `cron_evaluate_all_live_events` (ok + counters),
`cron_poll_slesh_for_all_live_events`, `cron_generate_reports_…`,
`cron_refresh_customer_intelligence_…` (ok + enqueue/skip counts),
`refresh_customer_intelligence` (bare `{"status":"ok"}`).

### The honest exceptions — proof the codebase knows how

`retrain_predictor` and `retrain_demand_predictor` return genuinely
distinct outcomes (`ok` / `no_completed_events_with_revenue` /
`no_training_data` / `error`), and `generate_report`'s failures at the
row level ARE durable (the report row is marked `failed`, visible in
the UI) even though its task status is not.

## Proposed remediations (approved as findings; implementation gated)

Deliberately not yet implemented — the ruling is to observe honest
behaviour first, then instrument around what is actually seen.

1. **Ingestion rule** — in `poll_slesh_orders`, before the
   success/failure recording decision:
   `orders_seen > 0 and orders_ingested == 0 and lines_errors > 0` →
   `failed` (and `record_failure`, so `consecutive_failures` climbs and
   the health pill goes honest); `lines_errors > 0` with partial
   ingestion → `degraded`. The cursor still advances (not advancing
   wedges the poller on poison orders; `ingestion_line_errors` is the
   replay record). All-parked cycles stay `ok` — parking has its own
   alert channel. Caveat: this rule catches *seen-but-failed*; the
   July-5 class (*unseen-or-misfiled* orders) is only catchable by
   reconciliation against provider totals — both classes belong in the
   remediation, unconflated.
2. **Features rule** — `populate_customer_features`: `failed` when the
   event has confirmed orders but `sessions_created == 0`. Denominator
   must be confirmed orders, NOT identified orders — the identified
   count is computed by the same expression whose failure this rule
   exists to catch.
3. **Before changing what 'ok' means in production**, run the read-only
   check of what production has been swallowing:
   `SELECT error_type, count(*) FROM ingestion_line_errors GROUP BY 1` —
   zero rows means the semantics change is quiet; anything else is a
   finding to have deliberately rather than by surprise.
4. **`end_event()` observability, two tiers** — Tier 1, no code change:
   each of the three jobs leaves a durable artifact whose presence IS
   the outcome (`customer_sessions` rows for the event; a
   `model_artifacts` row per model newer than `ended_at`) — three
   EXISTS queries make the pipeline observable retroactively for every
   event that ever ran. Tier 2, gated: an append-only job-outcomes
   table written from the tasks' existing success/except tails.
   `keep_result` must never be raised — it must stay below the poll
   cadence (see scheduler.py's history note).
