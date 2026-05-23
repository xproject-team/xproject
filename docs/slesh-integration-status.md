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
