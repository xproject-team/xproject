# XProject — Slesh Integration Roadmap

> **Living document.** This is the master reference for the Slesh integration phase. Every step gets a checkbox. Every completion gets a date and commit hash. When you don't know where you are, look at the **Status Pointer** below.

---

## 🧭 Status Pointer (UPDATE AS YOU GO)

**Phase:** ✅ INTEGRATION COMPLETE — Slesh fully integrated end-to-end
**Current step:** All 8 branches shipped. Real Sundance data flowing into the live dashboard.
**Branch:** `develop` (no active feature branch)
**Last update:** 2026-05-04
**Last update:** 2026-05-02
**Blockers:** None

> **How to update this section:** When you start a step, change "Not started" to "In progress." When a branch finishes, update Phase to the next branch. Keep it short — this is the dashboard, not the log.

---

## 📋 The 8 Branches at a Glance

| # | Branch | Focus | Risk | Effort | Status |
|---|---|---|---|---|---|
| **B1** | `feat/slesh-b1-config` | Token & config plumbing | Low | ~2 h | ✅ Done (a8e0b51) |
| **B2** | `feat/slesh-b2-adapter-contract` | Adapter ABC + Pydantic schemas + fixtures | Low | ~6 h | ✅ Done (d2a9739) |
| **B3** | `feat/slesh-b3-adapter-impl` | Real adapter (httpx + retry + rate limit) | Low | ~6 h | ✅ Done (f20ddff) |
| **B4** | `feat/slesh-b4-schema-migrations` | `external_pos_id` migrations | Low | ~1 h | ✅ Done (7fad547) |
| **B5** | `feat/slesh-b5-reference-sync` | Sync shops/products/categories from Slesh | Medium | ~5 h | ✅ Done (e9e25e8) |
| **B6** | `feat/slesh-b6-order-poller` | The polling worker (core: B6.1-B6.6) | High | ~10 h | ✅ Core done (3876248) — tests deferred |
| **B7** | `feat/slesh-b7-historical-backfill` | Replay past event + 4 root-cause perf fixes | Medium | ~5 h | ✅ Done (7b6c11b) |
| **B8a** | `feat/slesh-b8-frontend-freshness` | Freshness indicator | Low | ~3 h | ✅ Done (2e9aeea) |
| **B8b** | `feat/slesh-b8-wristband-activity` | Wristband Activity feed + payment_type column | Low | ~5 h | ✅ Done (626d0d7) |

**Total estimated effort:** ~43 hours (~9 working days at 5 h/day, ~6 days at 7 h/day)

**Status legend:** 🔵 Next · 🟢 In progress · ✅ Done · ⏸ Pending · ⚠️ Blocked · ❌ Reverted

---

## 🛡️ Standards Every Branch Must Meet

Before any branch is merged into `develop`, all five must be true:

- [ ] All existing tests still pass (no regressions)
- [ ] New code has its own tests (smoke + unit at minimum)
- [ ] Errors handled gracefully (no unhandled exceptions reach production)
- [ ] Logged at appropriate level (INFO for happy path, WARNING/ERROR for problems)
- [ ] Commit message follows conventional commits style (`feat(slesh): ...`, `fix(slesh): ...`, etc.)

**Test discipline:** "Medium" — smoke test + unit tests + run before commit. Allow ~15-20 min per step for testing.
**Backup discipline:** Git branches only. No file-level `.backup` copies in the repo.

---

## ⚠️ Sundance Readiness Lens

Every branch is held to one question: **"If Sundance happened tomorrow, does this code work safely under load?"**

If the answer is "no" or "I don't know," the branch is not done. This applies even to the early "low risk" branches.

---

# 🗺️ DETAILED BRANCH PLANS

---

## 🔵 B1 — Token & Config Plumbing

**Goal:** Settings class loads `SLESH_API_TOKEN`, `SLESH_BRAND_ID`, base URL, and operational knobs. Smoke test + unit test confirm.

**Files affected:**
- `backend/app/core/config.py` (modify)
- `backend/tests/core/test_config.py` (new)

**Pre-flight check:**
- [ ] Working tree clean (`git status --short` returns nothing)
- [ ] On `develop` branch
- [ ] `.env` contains `SLESH_API_TOKEN` and `SLESH_BRAND_ID`

**Steps:**

- [x] **B1.1** — Create feature branch `feat/slesh-b1-config` off `develop`
- [x] **B1.2** — Remove placeholder fields `slesh_api_url`, `slesh_api_key` from `Settings` class
- [x] **B1.3** — Add new Slesh fields:
  - `slesh_base_url: str = "https://api.slesh.it/api"`
  - `slesh_api_token: str = ""` (loaded from env)
  - `slesh_brand_id: str = ""` (loaded from env)
  - `slesh_request_timeout: float = 10.0`
  - `slesh_rate_limit_rps: int = 5`
  - `slesh_max_retries: int = 3`
- [x] **B1.4** — Smoke test: token loaded (201 chars), brand ID validated (24-char hex), all 6 assertions passed
- [x] **B1.5** — Created `backend/tests/test_config.py` with 7 tests (project uses flat tests/, not nested tests/core/)
- [x] **B1.6** — Ran tests: 7 passed in 0.01s
- [x] **B1.7** — Full regression: 9 passed (7 new + 2 pre-existing reports tests), 0 failed
- [x] **B1.8** — Committed: `feat(slesh): add Slesh API config fields and unit tests`
- [x] **B1.9** — Pushed branch: `git push -u origin feat/slesh-b1-config`
- [x] **B1.10** — Merged to `develop` (fast-forward), local branch deleted

**Done when:** All B1.x boxes checked, commit hash recorded below.

**Completion record:** `[done] 2026-05-01 — commit a8e0b51`

---

## 🔵 B2 — Adapter Contract + Pydantic Schemas + Fixtures

**Goal:** Replace the wrong-shaped `BasePOSAdapter` ABC with the read-only contract. Build Pydantic models for every Slesh response shape we use. Set up the fixture-based testing infrastructure that replaces the missing sandbox.

**Files affected:**
- `backend/app/modules/pos/adapters/base.py` (rewrite)
- `backend/app/modules/pos/adapters/slesh.py` (skeleton — implementation lands in B3)
- `backend/app/modules/pos/schemas.py` (new — Pydantic models for Slesh)
- `backend/app/modules/pos/converters.py` (new — money/timestamp boundary conversions)
- `backend/tests/fixtures/slesh/` (new directory — recorded responses)
- `backend/tests/modules/pos/test_schemas.py` (new)
- `backend/tests/modules/pos/test_converters.py` (new)

**Steps:**

- [x] **B2.1** — Branch `feat/slesh-b2-adapter-contract` created
- [x] **B2.2** — Rewrote `base.py` with 5 read-only methods (verify_token, list_shops, list_categories, list_products, list_orders); old wrong-shaped methods removed
- [x] **B2.3** — Created `schemas.py` with 11 Pydantic models (Brand, Shop, ShopAddress, Category, Product, CartLine, Payment, User, ShopRef, ExperienceRef, Order). Pythonic alias mapping (_id → id, _createdAt → created_at). Lenient + log strategy via extra='allow' + module-level dedup of unknown-field warnings.
- [x] **B2.4** — Created `converters.py` with 6 functions: cents_to_decimal, decimal_to_cents, unix_ms_to_datetime, datetime_to_unix_ms, to_europe_rome, localized_name. Money is Decimal (never float). Locale cascade: it → en → any → ''. Warning dedup at module level.
- [x] **B2.5** — Created `tests/fixtures/slesh/` directory + README + extended `conftest.py` with `slesh_fixture` helper.
- [x] **B2.6** — Recorded 5 real Slesh fixtures (brand, shop, category, product, order_brand_my). PII redacted (emails, phones, VAT, addresses, wristband tags).
- [x] **B2.7** — `slesh.py` rewritten as concrete skeleton: subclasses BasePOSAdapter, all 5 methods raise NotImplementedError pointing at B3. Importable, instantiable.
- [x] **B2.8** — Wrote `test_schemas.py`: 23 tests covering all 5 schemas, alias mapping, lenient strategy, and the 4 real-world quirks discovered during fixture validation.
- [x] **B2.9** — Wrote `test_converters.py`: 25 tests covering money (parametrized), timestamps (UTC + Rome), localized name cascade, and the warning-dedup regression.
- [x] **B2.10** — Ran new tests: 23 + 25 = 48 passed (parametrized expands further to ~50 cases).
- [x] **B2.11** — Full regression: **57 passed, 0 failed, 0.37s** total runtime.
- [x] **B2.12** — Committed: `feat(slesh): adapter contract, schemas, converters, and fixture-based tests` (14 files, 2056+/15-).
- [x] **B2.13** — Pushed branch, fast-forward merged to `develop`, local branch deleted.

**Sandbox-defense note:** B2.5 and B2.6 implement Layer 2 of the 4-layer sandbox-defense strategy.

**Completion record:** `[done] 2026-05-01 — commit d2a9739`

---

## ⏸ B3 — Real Adapter Implementation

**Goal:** Replace the `NotImplementedError` skeleton from B2 with a working httpx-based client. Add rate limiting, retry, and circuit breaker. End with one safe live integration test.

**Files affected:**
- `backend/app/modules/pos/adapters/slesh.py` (full implementation)
- `backend/app/modules/pos/client.py` (new — httpx wrapper)
- `backend/app/modules/pos/limiter.py` (new — token bucket rate limiter)
- `backend/app/modules/pos/retry.py` (new — backoff + circuit breaker)
- `backend/tests/modules/pos/test_adapter_unit.py` (new — fixture-based)
- `backend/tests/modules/pos/test_adapter_live.py` (new — sparing live calls)

**Steps:**

- [x] **B3.1** — Branch `feat/slesh-b3-adapter-impl` created
- [x] **B3.2** — `client.py` (215 lines): httpx async wrapper, bearer auth, JSON parsing, 5 typed exceptions. Read-only by construction (only `get()` exists). `trust_env=False` to avoid stale local proxy state. **IPv4-only transport** to sidestep half-broken IPv6 on institutional networks (Cloudflare-fronted Slesh + asyncio = 'Connection reset' without happy-eyeballs fallback).
- [x] **B3.3** — `limiter.py` (109 lines): token-bucket rate limiter, 5 req/s default, burst-friendly, monotonic time. Behavioral test verified 5-instant-then-200ms-throttle.
- [x] **B3.4** — `retry.py` (286 lines): RetryPolicy + CircuitBreaker (closed/open/half_open). Retries 429/5xx/network only. Hystrix-standard thresholds: 5 fails → open, 60s cooldown, 1 probe. 6 behavioral tests verify state transitions.
- [x] **B3.5** — `slesh.py` rewritten: composes client + limiter + retry. Two explicit pagination helpers (`_get_paginated` for shops/orders, `_get_list` for categories/products). Async generator `list_orders`. brand_id auto-injected. async context manager. `from_components()` for tests.
- [x] **B3.6** — Cross-module verification: 7 sub-modules, 25 public symbols, all import cleanly; B1+B2 tests still 55/55.
- [x] **B3.7** — `test_adapter_unit.py` (321 lines, 16 tests): fixture-based via in-file FakeSleshHTTPClient. Covers verify_token list-unwrap, multi-page pagination, brand_id injection, plain-list parsing, defensive shape checks, async generator, datetime conversion, context manager, stalled-pagination guard.
- [x] **B3.8** — Unit tests run: 16 passed in 0.03s.
- [x] **B3.9** — `test_adapter_live.py` (86 lines, 1 test): `verify_token` against real Slesh, marked `@pytest.mark.live`, auto-skips without token.
- [x] **B3.10** — Live test run successfully against real Slesh `/brand/my`: **0.40s end-to-end**. First Sundance-brand parse from real production data through the full B3 stack.
- [x] **B3.11** — Created `pytest.ini` registering the `live` marker + `addopts = -m "not live"` so default runs skip live tests. Full regression: **73 passed, 1 deselected, 0 failed in 0.43s**.
- [x] **B3.12** — Committed: `feat(slesh): real adapter with httpx + rate limiter + retry + circuit breaker` (7 files, 1300+/36-).
- [x] **B3.13** — Pushed branch.
- [x] **B3.14** — Fast-forward merged to `develop`, local branch deleted.

**Sandbox-defense note:** B3.3, B3.4 implement Layer 1 (read-only by construction) and Layer 3 (sparing live tests).

**Completion record:** `[done] 2026-05-01 — commit f20ddff`

---

## ⏸ B4 — Schema Migrations

**Goal:** Add `external_pos_id` columns to `products` and `categories` tables, mirroring the `bars.slesh_negozio_id` pattern.

**Files affected:**
- `backend/alembic/versions/l1_add_external_pos_id_to_products.py` (new)
- `backend/alembic/versions/l2_add_external_pos_id_to_categories.py` (new) [if categories table exists; verify first]
- `backend/app/modules/products/models.py` (add column)
- `backend/app/modules/products/schemas.py` (add field)
- `backend/app/modules/products/repository.py` (handle new field)

**Steps:**

- [x] **B4.1** — Branch `feat/slesh-b4-schema-migrations` created
- [x] **B4.2** — Confirmed: products.category is an ENUM column, NOT a separate categories table. So only ONE migration needed.
- [x] **B4.3** — Created migration `l1_add_external_pos_id_to_products`: ALTER TABLE products + CREATE INDEX. Reversible downgrade.
- [x] **B4.4** — N/A (categories is an enum, not a table)
- [x] **B4.5** — Updated `Product.external_pos_id: Mapped[str | None]` (mirrors bars.slesh_negozio_id)
- [x] **B4.6** — Updated all 3 Pydantic schemas: ProductResponse, ProductCreate, ProductUpdate (max_length=128)
- [x] **B4.7** — Updated `Repository.create()` to persist external_pos_id; `update()` handles it via existing model_dump auto-loop
- [x] **B4.8** — Ran migration: caught and fixed `alembic_version VARCHAR(32)` overflow by shortening revision ID from 38 to 25 chars
- [x] **B4.9** — Verified column + index in DB via `psql \d products`
- [x] **B4.10** — Round-trip verified: downgrade removes column cleanly, upgrade restores it
- [x] **B4.11** — Full regression: 73 passed, 1 deselected, 0 failed (0.39s)
- [x] **B4.12** — Committed: `feat(slesh): add external_pos_id to products (Slesh linkage)` (4 files, 61+/0-)
- [x] **B4.13** — Pushed, fast-forward merged to develop, local branch deleted

**Completion record:** `[done] 2026-05-01 — commit 7fad547`

---

## 🔵 B5 — Reference Data Sync (One-Shot CLI)

**Goal:** A CLI command that pulls all shops, categories, and products from Slesh for a given brand/experience and upserts them into our DB. First time we see real Slesh data populated locally.

**Files affected:**
- `backend/app/scripts/sync_slesh_reference.py` (new)
- `backend/app/modules/pos/sync_service.py` (new — orchestrates the sync)
- `backend/tests/modules/pos/test_sync_service.py` (new)

**Steps:**

- [x] **B5.1** — Branch `feat/slesh-b5-reference-sync` created
- [x] **B5.2** — `sync_service.py`: 2 methods (sync_shops + sync_products). Categories handled via in-code enum mapping — no separate sync needed since our schema treats categories as enum values, not a table.
- [x] **B5.3** — CLI `sync_slesh_reference.py` with --tenant-slug + --event-id + --experience-id + --skip-shops/products. Verifies token first, then runs both syncs in a single transaction.
- [x] **B5.4** — `test_sync_service.py`: 14 unit tests (parametrized category classification, SyncResult arithmetic, warning behavior, whitespace tolerance).
- [x] **B5.5** — First live run: 21 shops + 66 products created from real Slesh data
- [x] **B5.6** — Verified in DB: 21 bars (Ape Magna, Bar Barcelo, Cocktail Bar, Focacceria, etc.), 66 products by type (14 drink + 48 food + 4 supply) with real prices
- [x] **B5.7** — Idempotency confirmed: re-run produces created=0, all skipped
- [x] **B5.8** — Full regression: 87 passed, 1 deselected, 0 failed (0.35s)
- [x] **B5.9** — Committed: `feat(slesh): reference data sync — shops + products` (5 files, 555+/5-)
- [x] **B5.10** — Pushed, fast-forward merged to develop, local branch deleted

**Real-world quirks discovered & fixed during B5.5:**
1. Slesh `from` query param is 1-indexed (minimum 1). from=0 returned 400. Fixed in _iter_paginated.
2. Slesh returns Product.category as bare ID by default; needs `?populatedField=category` to get the full Category dict. Threaded populated_field through list_products.

**Completion record:** `[done] 2026-05-01 — commit e9e25e8`

---

## 🔵 B6 — Order Polling Worker (THE CORE)

**Goal:** The arq job that polls `GET /order/brand-my` on a schedule, maps cart line items into `stock_transactions`, and lets the existing 7-step ingestion pipeline take over from there. **This is the single most important branch in the entire integration.**

**Files affected:**
- `backend/app/workers/slesh_poller.py` (new)
- `backend/app/modules/pos/order_ingester.py` (new — maps Order → stock_transactions)
- `backend/app/modules/pos/poll_state.py` (new — tracks last-seen timestamps per brand/experience)
- `backend/alembic/versions/l3_add_slesh_poll_state.py` (new — small table for cursor tracking)
- `backend/tests/modules/pos/test_order_ingester.py` (new)
- `backend/tests/modules/pos/test_slesh_poller.py` (new)

**Steps:**

- [ ] **B6.1** — Branch `feat/slesh-b6-order-poller`
- [ ] **B6.2** — Create `slesh_poll_state` table migration: stores `(brand_id, experience_id, last_seen_ts, last_run_ts, last_status)`
- [ ] **B6.3** — Build `order_ingester.py`:
  - `ingest_order(order: Order) -> list[StockTransaction]`
  - One stock_transaction per cart line, source=`SLESH_POS`
  - Idempotency key: `slesh:{order._id}:{cart_line._id}`
  - Cents → Decimal at boundary
  - Unix ms → datetime at boundary
  - Localized name → name.it
- [ ] **B6.4** — Build `poll_state.py` with overlap-window logic:
  - On each poll, ask for `[last_seen − 60s, now]` (Resilience Pattern P1)
  - Save new `last_seen` only after successful ingest of all returned orders
- [ ] **B6.5** — Build `slesh_poller.py` arq job:
  - Variable cadence: 30s during live events, 5min off-hours (P2)
  - Calls `adapter.list_orders(...)` with overlap window
  - For each order, calls `order_ingester.ingest_order(order)`
  - Writes to `stock_transactions` (DB unique constraint deduplicates)
  - Pagination-aware catch-up after gaps (P4)
  - Circuit breaker on repeated failures
- [ ] **B6.6** — **Manual trigger only** for now — not auto-scheduled. (Auto-schedule lands in a later step.)
- [ ] **B6.7** — Unit tests against fixtures: ingester logic, idempotency, edge cases (refunded line, missing fields, duplicate order)
- [ ] **B6.8** — Integration test: trigger poller manually for a past 1-hour window, verify orders appear in DB
- [ ] **B6.9** — Spot-check: pick 3 orders from Slesh, verify each appears with correct fields in our DB
- [ ] **B6.10** — Verify dashboard now shows real data (this is the "moment of truth")
- [ ] **B6.11** — Test idempotency: trigger poller twice on same window — second run should produce 0 new rows
- [ ] **B6.12** — Test outage handling: simulate a failed poll (kill the network mid-call), verify circuit breaker engages
- [ ] **B6.13** — Run full regression
- [ ] **B6.14** — Commit: `feat(slesh): add order polling worker with overlap-window and idempotency`
- [ ] **B6.15** — Push, merge to `develop`, delete branch

**Resilience patterns implemented in B6:** P1 (overlap window), P2 (variable cadence), P4 (pagination catch-up).

**⚠️ This is the highest-risk branch.** Allow extra time for testing.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

## ⏸ B7 — Historical Backfill of One Past Event

**Goal:** Use the same poller in catch-up mode to replay a past Sundance Sunday into our DB. Validates the pipeline end-to-end with real historical data and produces strong demo material.

**Files affected:**
- `backend/app/scripts/backfill_slesh_event.py` (new)
- `backend/tests/scripts/test_backfill.py` (new)

**Steps:**

- [ ] **B7.1** — Branch `feat/slesh-b7-historical-backfill`
- [ ] **B7.2** — Build CLI: `backfill_slesh_event.py --experience-id <id> --from-ts <iso> --to-ts <iso>`
- [ ] **B7.3** — Reuses `order_ingester.py` from B6 (no new ingestion logic)
- [ ] **B7.4** — Pages through Slesh, ingests every order in window
- [ ] **B7.5** — Logs progress every N orders (so we can watch it work)
- [ ] **B7.6** — Idempotent — safe to re-run
- [ ] **B7.7** — Run on a past Sundance event (~6-8 hour window)
- [ ] **B7.8** — Spot-check: total revenue from our DB vs. expected (Omar can validate)
- [ ] **B7.9** — Spot-check: top product, top bar, peak hour all match expectations
- [ ] **B7.10** — Run full regression
- [ ] **B7.11** — Commit: `feat(slesh): add historical event backfill CLI`
- [ ] **B7.12** — Push, merge to `develop`, delete branch

**Demo win:** "Hesam, here's what your dashboard would have shown during last September's Sundance — built from real Slesh data."

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

## ⏸ B8 — Frontend Freshness Indicator + Wristband Activity

**Goal:** Two visible-to-Omar improvements. (1) Data freshness indicator on dashboard header. (2) Wristband Activity panel — the reframed Delta 4 that replaces the impossible "balance display."

**Files affected (backend):**
- `backend/app/modules/pos/router.py` (new endpoint `GET /api/v1/sync/status`)
- `backend/app/modules/pos/wristband_view.py` (new — derived view)
- `backend/app/modules/pos/wristband_router.py` (new — endpoint for wristband activity)
- `backend/tests/modules/pos/test_wristband_view.py` (new)

**Files affected (frontend):**
- `frontend/src/features/dashboard/components/SyncStatusBadge.tsx` (new)
- `frontend/src/features/dashboard/hooks.ts` (add `useSyncStatus`)
- `frontend/src/features/wristbands/...` (new feature folder)
- `frontend/src/features/dashboard/BarDashboardView.tsx` (integrate panel)

**Steps:**

- [ ] **B8.1** — Branch `feat/slesh-b8-frontend-freshness`
- [ ] **B8.2** — Backend: `GET /api/v1/sync/status` returns `{last_poll_at, lag_seconds, status: "live" | "delayed" | "down", next_poll_at}`
- [ ] **B8.3** — Backend: query for wristband activity (group orders by `user.tag` where `payment._type = 'token'`)
- [ ] **B8.4** — Backend: endpoint `GET /api/v1/events/{eid}/wristband-activity?bar_id=&limit=`
- [ ] **B8.5** — Frontend: `SyncStatusBadge` component: green (live, <30s), yellow (delayed, 30s-5min), red (down, >5min)
- [ ] **B8.6** — Frontend: `useSyncStatus` hook polls the endpoint every 5s
- [ ] **B8.7** — Frontend: integrate badge into dashboard header
- [ ] **B8.8** — Frontend: build `WristbandActivityPanel` — top spenders, drink preferences, multi-bar visit patterns
- [ ] **B8.9** — Frontend: Italian-localized labels everywhere
- [ ] **B8.10** — Manual UI walkthrough: dashboard refresh shows live state; wristband panel shows real data
- [ ] **B8.11** — Backend tests + frontend tests
- [ ] **B8.12** — Run full regression
- [ ] **B8.13** — Commit: `feat(slesh): add data freshness indicator and wristband activity panel`
- [ ] **B8.14** — Push, merge to `develop`, delete branch

**Resilience patterns implemented in B8:** P6 (graceful degradation UI).

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# 📦 Deferred Features (the "later, smartly" list)

These are intentionally NOT in the 8-branch sequence. Each has a smart workaround already built or a clear path forward.

| Deferred feature | Why deferred | Smart workaround |
|---|---|---|
| Wristband balance display | No Slesh endpoint exists | Replaced by Wristband Activity (B8); request endpoint from Alberto for v1.5 |
| Real-time webhook stream | Slesh has no webhooks | Polling at 30s is acceptable for Omar's use cases; request webhooks for v1.5 |
| Top-up event stream | No `/wallet/topup` endpoint | Inferred from `payment._type = 'token'` orders |
| Per-customer demographic data | Only retrievable per-order | Defer until specific use case emerges |
| Sub-second push alerts | Polling cadence makes <30s impossible | Variable cadence (15s during peaks); existing WebSocket pushes from our backend |

---

# 🎯 Sundance Readiness Checklist (BEFORE event day)

Independent of branches — must all be true before June 14:

- [ ] All 8 branches merged into `develop`
- [ ] All resilience patterns (P1-P8) implemented and tested
- [ ] At least one full historical event backfilled successfully
- [ ] Reconciliation pass implemented and runs hourly without errors
- [ ] Graceful degradation tested under simulated Slesh outage
- [ ] Token rotation procedure documented (in case the production token is compromised)
- [ ] Omar walked through the dashboard during a dry run
- [ ] Polling worker auto-schedules for Sundance event window
- [ ] Backup channel for "Slesh totally down" agreed with Alberto

---

# 📝 Decision Log

When we make a decision while building, log it here so we don't forget the "why."

| Date | Decision | Why | Affected |
|---|---|---|---|
| 2026-04-29 | Activate Plan B (polling) instead of Plan A (webhook) | Slesh has no webhooks; Plan B already documented in original Bible §4.4 | Architecture |
| 2026-04-29 | Reframe wristband balance → wristband activity | No balance endpoint; activity is richer anyway | B8, MVP scope |
| 2026-04-29 | Read-only adapter by construction | No write endpoints needed; eliminates risk class | B3 |
| 2026-04-29 | Use fixtures + sparing live tests instead of sandbox | Slesh has no sandbox | B2, B3 |
| 2026-04-29 | Keep `pos/` module name (not `slesh_pos/`) | "POS" describes what, vendor lives in adapter file | B2 |
| 2026-04-30 | Test discipline: medium (smoke + unit, ~15-20 min) | Balances thoroughness with pace | All branches |
| 2026-04-30 | Backup discipline: git branches only, no `.backup` files | Trust git, not file copies | All branches |
| 2026-04-30 | Branch strategy: short-lived per component | Reviewable, revertable, testable independently | All branches |
| 2026-05-01 | Slesh API has 2 response shapes: paginated `{docs:[...]}` for shops/orders, plain list `[...]` for categories/products | Discovered during B2.6 fixture recording — undocumented quirk | B3 adapter implementation |
| 2026-05-01 | Sundance scale: 21 shops, 5 categories, 84 products, 38,046 historical orders | Reality is bigger than initial assumption (4-5 bars); architecture handles it but informs UI density and backfill scope | B5 sync, B7 backfill, frontend |
| 2026-05-01 | Slesh added `cleanWalletsOnExperienceEnded` field overnight | Lenient+log strategy absorbed it cleanly with zero crashes — validates the design choice | Brand schema (defer update) |

---

# 🔗 Related Documents

- `docs/event-page-flow.md` — Event state machine (frozen, no changes from this sync)
- `docs/chat-module-spec.md` — Chat module spec (frozen, no changes)
- `XProject_Slesh_Investigation_Report.pdf` — Full investigation findings (Apr 29)
- `XProject_Slesh_Sync_Plan.pdf` — Strategy document (Apr 29)
- `XProject_Strategia_Ambiente_Sandbox_OMAR.pdf` — Sandbox strategy doc for Omar (Apr 29)
- `XProject_MVP_v2_1_FINAL_ENGLISH.pdf` — MVP scope (frozen)

---

# 📌 Quick Commands Reference

```bash
# Where am I?
cd ~/Projects/xproject && git branch --show-current && git status --short

# Start a new branch
git checkout develop && git pull && git checkout -b feat/slesh-bX-name

# Run all tests
cd ~/Projects/xproject/backend && pytest

# Run only Slesh-module tests
pytest backend/tests/modules/pos/

# Run a single test file
pytest backend/tests/core/test_config.py -v

# Smoke test config (B1)
python -c "from app.core.config import settings; print(len(settings.slesh_api_token))"

# Manually trigger reference sync (B5)
python -m app.scripts.sync_slesh_reference --experience-id <id>

# Manually trigger backfill (B7)
python -m app.scripts.backfill_slesh_event --experience-id <id> --from-ts <iso> --to-ts <iso>
```

---

**End of roadmap. Update the Status Pointer at the top whenever your position changes.**
## Token Rotation Reminder

**Pre-Sundance task:** rotate the Slesh API token before June 14, 2026.
Current token leaked into AI chat scrollback during B7 debugging on 2026-05-03.
Risk: read-only access only; one private chat exposure. Rotate via email to product@team.slesh.it.
