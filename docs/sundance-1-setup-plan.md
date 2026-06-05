# XProject — Sundance 1 Setup Plan

**Created:** 2026-06-02 (after S5 e2e validation + 042fd06 alerts fix)
**Target:** Sundance Sunday — **2026-06-14** (Saturday)
**Days available:** 9 from creation date (full-availability mode)

## Context

After tonight's 6 commits (S2 + S3 + S4 backend + 042fd06 alerts fix +
S5 simulator + f81b2f6 seed union), Omar provided his official Slesh
**Project Plan — Cashless** Excel for Sundance Sunday 2026. This doc
is the analysis + roadmap to take XProject from "validated platform"
to "Sundance 1 ready" using Omar's template as the single source of truth.

**Key direction from Omar:**
1. "Sink with Slesh" — Slesh is authoritative for cashless; XProject mirrors
2. Staff list comes separately tomorrow
3. Recipes: category-level "global ML scope" not per-product
4. Sundance 1: manual bottle-count entry per bar (no QR yet)
5. Sundance 2 (July 5): QR warehouse system
6. Food bars need their OWN BarCard variant (different layout)

## Omar's Excel (6-sheet Slesh template)

| # | Sheet | Filled | Purpose |
|---|-------|--------|---------|
| 1 | Overview | ~42 rows | Event metadata, venue, contacts, Stripe, wristbands |
| 2 | Parametri Evento | 12 | Top-up amounts + refund policy |
| 3 | Device Count | ~25 | POS devices per bar (26 total) |
| 4 | Listini Bar | 88 | Products + prices + IVA + cauzione |
| 4.1 | Listini Food | 22 | Food shops (Malandrino, Scrocchia, Pulled Pork) |
| 5 | Lineup | 28 | 3 stages × 5 slots (artists TBD) |

### Overview key fields
- Event: Sundance Sunday, 12:30–22:30, staff arrives 11:00
- 4 dates 2026: **14/06**, 05/07, 19/07, 02/08
- Venue: Villa Alberico, Via di Fioranello 18 Roma, capacity 1600
- Stripe ragione sociale: Sundance srls
- Wristbands: 1800 × 4 types = 7200 total

### Parametri Evento
- User top-up: €5/10/20/50/100  | Staff: €5 single
- Refund min credit €1, fee €0.50, window TBD

### Device Count (26 total)
- Cassa (4), MAIN BAR (9), NO.3 BAR (1), STAGE BAR (4)
- Food trucks: Malandrino (2), Scrocchia (2), Pulled Pork (2)
- Accrediti ingresso (2)

## Gap analysis: Excel → DB

| Field | Status | Action |
|-------|--------|--------|
| Event.stripe_ragione_sociale | ❌ | NEW varchar(255) |
| Event.staff_arrival_time | ❌ | NEW time-only |
| Event.wristband_qty_per_type | ❌ | NEW JSONB |
| Event.topup_denominations_user | ❌ | NEW JSONB array (cents) |
| Event.topup_denominations_staff | ❌ | NEW JSONB array |
| Event.refund_min_credit_cents | ❌ | NEW int |
| Event.refund_fee_cents | ❌ | NEW int |
| Event.refund_window_open_at / close_at | ❌ | NEW timestamptz × 2 |
| Bar.device_count | ❌ | NEW int |
| Bar.slesh_category | ⚠️ | Have bar_type; add slesh_category for fidelity |
| Product.iva_pct | ❌ | NEW numeric(4,3) default 0.100 |
| Product.cauzione_cents | ❌ | NEW int nullable |
| Stage + LineupSlot tables | ❌ | NEW (deferrable) |

Slesh template does NOT cover (XProject value-add layer):
- Inventory allocations (bottle counts per bar)
- Staff rosters (incoming tomorrow)
- Recipes (using category-level scope per Omar)

## 10-phase roadmap

**Phase A — Analysis & alignment** ✅ DONE
Decoded 6-sheet template, mapped 14 new fields + 2 partial overlaps.

**Phase B — Schema extensions** (3 migrations)
- Event extensions (9 cols), Bar (device_count + slesh_category),
  Product (iva_pct + cauzione_cents), Stage+LineupSlot (deferrable)
- All NULL-safe defaults, 191 tests stay green

**Phase C — Inventory feature (manual mode)**
- Inventory Allocation page: grid bars × products, edit allocated_qty
- POST /api/v1/bar-stock/bulk-allocate
- Excel/CSV paste-in
- QR version → Sundance 2 backlog

**Phase D — Create Event wizard (7 tabs mirroring Slesh)**
1. Overview  2. Parametri  3. Device Count  4. Bars  5. Listini
6. Inventory  7. Lineup
Plus Excel paste-in on Tabs 4+5, "Go LIVE" validation button.

**Phase D-bis — Food BarCard variant**
Different middle section when bar_type='food'.
Same wrapper, name, alert pill, overlay click.
Per-food-item counts instead of drink categories.
3-4 hours, NOT blocking critical path, high UX value.

**Phase E — Category-level alerts**
Verify DepletionEvaluator works at category granularity (it does post-042fd06).
Tune category-level thresholds.

**Phase F — Sundance 1 event setup**
- Wipe stale Sundance 2026 data in Omar's tenant
- Run new Create Event wizard with Omar's Excel data
- Allocate inventory via Phase C
- Pre-LIVE smoke: 100 tx + dashboard render

**Phase G — Pre-deployment test pass**
Frontend click-through, simulator replay, WebSocket push, full pytest.

**Phase H — Deploy** (1-2 days pre-event)
Hosting decision, PG prod, Redis + MinIO, arq worker, health checks.

**Phase I — Sundance 1 LIVE (June 14)**
Pre-event allocation review, press LIVE, monitor.

**Phase J — Post-Sundance retrospective**
Backlog for Sundance 2: QR warehouse, staff QR onboarding,
food revenue path, S4 frontend, recipe library, ML retrain.

## Open questions for Omar

1. Refund window dates (placeholder "xx/xx/2026" in Excel)
2. Lineup artists (all cells empty)
3. Wristband types: just quantities, or color/ticket-tier names?
4. Cauzione handling: refunded on return or kept?
5. MAIN BAR / NO.3 BAR / STAGE BAR — 1 bar with positions or 3 bars?
6. Staff CSV format
7. Confirm Sundance 1 = June 14 (not June 19)

## State

Repo: branch `develop`. 6 commits today. 191 tests passing.
