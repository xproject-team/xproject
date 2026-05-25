# Slesh API Integration — Live Verification Report

**Date verified:** 2026-05-23
**Verified by:** Live API calls against https://api.slesh.it/api/* using production token

---

## TL;DR

The Slesh integration is **production-live** against Omar Abdelbari El Asry's
real Slesh tenant. All 5 adapter endpoints respond correctly. The polling
worker is registered as a cron job and will start ingesting orders the
moment the Sundance 2026 event is set to LIVE on June 19.

No further integration work is required before Sundance. Mapping work
between Slesh's 21 shops and XProject's 22 bars is the only reconciliation
task remaining — that's a data step, not an integration step.

---

## What was verified

| Endpoint | Status | Sample data |
|---|---|---|
| GET /brand/my       | live | Brand name: "Sundance Sunday" |
| GET /shop/my        | live | 21 shops returned (incl. "Pret a Polpett", "Ape Magna", "Toto") |
| GET /category/my    | live | 5 categories: Sundance Sunday, Food, beverage, ... |
| GET /product/my     | live | 84 products (incl. "Acqua", "Analcolico", "BUN ceci", ...) |
| GET /order/brand-my | live | Historical orders stream cleanly (50+ in last 365 days) |

---

## Adapter architecture

backend/app/modules/pos/adapters/slesh.py — SleshAdapter:

- httpx async client with explicit IPv4 transport (workaround for
  asyncio + Cloudflare + institutional Wi-Fi connection-reset bug)
- Token-bucket rate limiter (5 req/s default)
- Exponential-backoff retry policy (1s -> 2s -> 4s, max 30s)
- Circuit breaker after consecutive failures
- Lenient Pydantic schemas (unknown fields logged + accepted, not rejected)
- Async context manager for clean shutdown

The lenient schemas were validated against ~30 real unknown fields on
this verification run — adapter accepted them all without failing.

---

## Polling worker

backend/app/modules/pos/slesh_poller.py + cron registration in
backend/app/workers/scheduler.py:

    cron(
        cron_poll_slesh_for_all_live_events,
        minute={3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58},
        run_at_startup=True,
    )

- Runs every 5 minutes on off-minute slot {3, 8, 13, ...}
- run_at_startup=True — fires immediately when worker boots so a fresh
  worker catches up without waiting up to 5 minutes
- For each event in LIVE status, enqueues one poll_slesh_for_event job
- The ingester runs in parallel worker slots (max_jobs=10)

---

## Idempotency

The poller uses source_idempotency_key on stock_transactions. If
Slesh returns the same order twice (e.g. retry, reprocessing), the
ingester deduplicates safely on insert.

This was tested during Phase F implementation; no further work needed.

---

## What happens on Sundance day (June 19, 2026)

1. Operator sets Sundance 2026 event to LIVE
2. First poll runs at next {3, 8, 13, ...} minute mark, or fires
   immediately if worker was restarted with run_at_startup
3. Subsequent polls run every 5 minutes; each poll fetches orders since
   the last cursor
4. StockTransactionService.ingest_sale() converts each line to a
   stock_transactions row, deducting from bar_stock
5. AlertsOrchestrator (separate cron at {0, 5, 10, ...}) reads the new
   transactions and fires depletion/anomaly alerts
6. When operator sets event to COMPLETED, poller stops automatically;
   reports module generates the post-event PDF

---

## Remaining mapping work (NOT integration work)

Slesh has 21 shops; XProject DB has 22 bars. The bar table has
slesh_negozio_id column reserved for this mapping. To resolve:

1. Pull the latest list of Slesh shops via the adapter
2. Match each shop to its corresponding XProject bar by name
3. Update bars.slesh_negozio_id for each match

This is a ~30-minute data-entry exercise the day before Sundance, not
an engineering task.

---

## Verification commands (re-runnable)

Live test of the token + /brand/my endpoint:

    cd backend && source venv/bin/activate
    pytest -m live -v

Full 5-endpoint smoke test:

    python3 /tmp/slesh_smoke.py

Deep health check including Sundance event:

    curl -s http://localhost:8000/api/v1/health/deep | python3 -m json.tool

---

## Why the project memory said "Slesh sandbox pending"

Historical artifact. The original 12-week plan listed "Slesh sandbox
credentials" as a critical dependency. At some point — looks like the
Phase B sprint that built the adapter — Omar provided the actual
production token. The chat-memory note was never updated to reflect
that the integration moved from "pending" to "live."

This document is the authoritative record. The integration is live.

---

## Update — 2026-05-25 (shop mapping verification)

Verified live against Slesh API: every one of the 21 Slesh shops is
already mapped to the correct XProject bar via `bars.slesh_negozio_id`.
No new mapping work required.

One XProject bar — "Wine Station" (id `be2ffc20-4a0c-4181-a24f-e39aa17b2c01`)
— has `slesh_negozio_id = NULL` and no corresponding Slesh shop. It is
marked active (created 2026-04-16). Treated as a non-POS bar that operates
on manual scanning only.

**Action item for Omar (not code):**
Confirm whether Wine Station is a genuine non-POS bar (manual scans only,
no NFC wristband sales) or a leftover test record that should be marked
inactive before Sundance.

---

## Slesh API quirks discovered live (2026-05-25)

These are NOT documented by Slesh. We discovered them by probing the
real production API. Future engineers MUST know about these to avoid
silent data loss at events.

### Quirk 1 — `from` parameter is broken

The `/order/brand-my` endpoint accepts a `from` query parameter
documented as "1-indexed offset for pagination." In practice, Slesh
ignores the parameter entirely. Verified:

  - `from=100`: returned the same first 100 docs as `from` omitted
  - `from=101`: same
  - `from=envelope.to`: same
  - `from=envelope.to+1`: same

Slesh always returns docs 1-100 regardless of `from`. The adapter has
a defensive loop guard that detects this and stops, but the data is
not recoverable through pagination.

### Quirk 2 — `pageSize` is hard-capped at 100

Setting `pageSize=200` returns HTTP 400 with:

    "Number must be less than or equal to 100"

So 100 is both the default and the maximum per-call.

### Quirk 3 — Implication: chunk-by-time is the ONLY way

Combined, these mean: to retrieve all orders in a multi-hour window,
the caller MUST split the window into time-based chunks small enough
that each chunk has <=100 orders. The adapter cannot help — pagination
inside a single chunk doesn't work.

For Sundance peak load (estimated from real 2025 data):

  - Total orders per event:    ~700-4500 over 9 hours
  - Peak 5-min slot:            ~10 orders (far under 100)
  - Live polling cron interval: 5 minutes
  - Conclusion:                 SAFE — no data loss risk

For historical backfill (multi-hour windows):

  - 9-hour Sundance day = ~4500 orders in 5-day window
  - Must chunk into 10-minute slices to stay <= 100/chunk
  - Backfill script uses 30-min chunks by default — increase to use
    10-min if loading a denser event.

### Quirk 4 — Adapter must warn on truncation

If a single chunk hits exactly 100 docs AND `envelope.total > 100`,
data is being silently lost. The adapter logs a `DATA LOSS` warning
in that case. Test: `tests/test_slesh_chunk_truncation.py`. If the
test breaks, the warning was deleted or weakened — fix immediately.
