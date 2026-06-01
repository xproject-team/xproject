# E2E Validation Build — Simulator + Missing Flow Pieces

**Date:** June 1, 2026 (T-18 days to Sundance)
**Author:** Hesam (CEO / tech lead)
**Status:** SCOPED — coding in progress

---

## Why this exists

Stop building features. PROVE the full live-event loop works
against real Slesh-shaped data before Sundance. The simulator
is the validation tool; the missing flow pieces are real
production code we needed anyway. Both ship together so we
can dry-run a full event end-to-end.

## What we are NOT doing

- ML predictions (paused — separate thread)
- Warehouse module changes
- Post-event reports
- v1.5 features (weather, no-show, etc.)

## What we ARE doing

Five workstreams. Order matters — earlier work unblocks later.

### S1 — Inventory the 2025 data (~30 min)

`~/Desktop/2025/` contains multiple event files. Before any code
we know:
  - file count + names + sizes
  - column schemas (likely vary across files)
  - timestamp format(s)
  - product naming conventions
  - which event(s) are usable for first simulator run

Outputs: short summary in `docs/2025-data-inventory.md`.

### S2 — Event schema upgrade (~1 day)

Events table currently has `scheduled_date` (a date, not a
datetime). Per Omar's requirement, replace with:

  - `scheduled_at`     DateTime, REQUIRED
  - `scheduled_end_at` DateTime, REQUIRED
  - keep `started_at`, `ended_at` (actuals — already exist)

Migration:
  - Alembic migration adds the two new columns (nullable=True
    initially), backfills scheduled_at = scheduled_date + 19:00
    for existing rows (assume 7pm default), then ALTER COLUMN
    SET NOT NULL.
  - Frontend event-create form: two datetime-local fields,
    both required, with validation (end > start, both > now,
    end-start ≤ 12 hours).
  - All existing endpoints that read scheduled_date keep
    working via a computed property OR are updated.

### S3 — Auto-go-live + auto-end crons (~half-day)

  - arq cron `cron_auto_transition_event_statuses`, minute={5},
    runs every 5 min.
  - Two responsibilities per run:
    
    1. DRAFT → LIVE: find events where
         status='draft' AND scheduled_at <= now()
       Promote to LIVE, set started_at = now().
    
    2. LIVE → COMPLETED: find events where
         status='live' 
         AND scheduled_end_at <= now()
         AND NOT EXISTS (transaction in last 60 min)
       Promote to COMPLETED, set ended_at = now().
       
       The 60-min-silence guard prevents a 3pm Slesh outage
       from accidentally ending a 7pm-3am event.

  - Manual buttons remain primary path; cron is fallback.
  - Owner manual go-live allowed in window:
       scheduled_at - 1 hour  <=  now  <=  scheduled_at
    Outside that window, button is disabled with a tooltip
    explaining why.

### S4 — Name-matching confirmation UX (~1 day)

When event goes LIVE and the first Slesh sync runs, for each
Slesh shop:
  - Try exact `slesh_negozio_id` match first (current behavior).
  - If no match, run fuzzy name match (rapidfuzz or stdlib
    SequenceMatcher) against bars in this event with
    slesh_negozio_id=NULL. Score >= 0.75 = candidate.
  - DO NOT auto-link. Store the candidate in a new table
    `slesh_shop_match_proposals`:
      (id, tenant_id, event_id, slesh_shop_id, slesh_shop_name,
       suggested_bar_id, similarity_score, status, decided_at,
       decided_by)
    status enum: pending / accepted / rejected / skipped.
  - Dashboard surfaces an "Approval Required" banner with one
    row per pending proposal: typed name vs Slesh name with
    [Accept] [Reject] [Skip] buttons.
  - On Accept: set bars.slesh_negozio_id = slesh_shop_id.
  - On Reject: create a NEW bar from the Slesh shop.
  - On Skip: leave pending; will resurface next sync.

### S5 — Simulator (~1 day)

Python CLI that replays a 2025 event into XProject:

  python -m app.scripts.simulate_event \\
    --input ~/Desktop/2025/<event-file> \\
    --target-event-id <uuid> \\
    --speed 60     # 60x = 1 real minute -> 1 sim second
    --mode http    # or db-direct (faster, less realistic)

Two modes:
  - `http`: POST each transaction to the XProject backend\'s
    Slesh-webhook endpoint (or `db-direct` if no webhook exists)
    on the original timeline scaled by --speed
  - `db-direct`: insert directly into stock_transactions with
    backdated timestamps; useful for unit testing the math

The simulator timeline:
  1. Reads input file, extracts (timestamp, bar, product,
     quantity, amount) tuples
  2. Normalizes timestamps relative to event start
  3. Replays in chronological order at --speed multiplier
  4. Logs every action so we can audit afterwards

Outputs:
  - Real-time log
  - Final summary: N transactions sent, X categorized as Y,
    bar XY received Z revenue
  - Optional: a "diff" report comparing simulator-injected
    totals vs what XProject computed

### S6 — Full dry run + bug fixes (~half-day)

Run S5 against a real 2025 file, watch the dashboard live in
Chrome. Note every weird behavior. Fix the top-priority ones.

## Crash-risk discipline for Sundance

Every commit in S2-S5:
  - Backend test added before merge
  - Frontend type-check passes
  - Migration tested on a DB snapshot before live
  - No silent dependency on optional environment variables

Sundance failure modes we are explicitly defending against:
  - Slesh outage mid-event (cron retries; alerts continue
    rendering with stale data, no crash)
  - Omar forgets to go live (auto-cron promotes at scheduled_at)
  - Bar name typo at event creation (name-matching UX catches it)
  - Old products from prior events polluting current view
    (PATH A+ filter excludes them)
