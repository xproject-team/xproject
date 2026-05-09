# XProject Scanner — System Design

**Status:** Approved 2026-05-08
**Owner:** Hesam (technical lead)
**Spec for Phase 6 of the Sundance Readiness Roadmap**

---

## 1. Why this exists

XProject's value proposition rests on real-time accuracy of bar-level
inventory. Today, stock movement is recorded via:

  - `allocate` — pre-event commit of N bottles to a bar
  - `consume` — POS sale (Slesh) or manual decrement
  - `return` — bottle moved back to warehouse

Accuracy gaps are large: bottles can disappear between warehouse and
bar (transit shrinkage), and POS-recorded consumption diverges from
actual physical depletion (over-pours, comp drinks, breakage, theft).

A barcode scanner closes both gaps by giving us two new ground-truth
event streams:

  - **Arrivals** — every full bottle that physically reaches a bar
  - **Empties** — every empty bottle pulled out of the bin after the
    event

Difference between these two streams (per product, per bar) IS the
shrinkage rate. Sum of these is the consumption rate. Both feed every
existing analytics surface: burn rate, depletion forecasts, anomaly
detection, post-event reports.

---

## 2. The three modes

### Mode A — Catalog Builder (one-time, pre-event, no Sundance pressure)

**Who:** Owner.
**When:** Before any event. Probably this week.
**Where:** Desktop or phone, leisure pace.
**Goal:** Build the barcode → product registry once. Reusable across
all future events because Noma's bottle inventory is stable.

**Workflow:**
  1. Open Catalog page, click "+ Add Product" (existing flow, extended).
  2. Type or scan barcode (13 digits for EAN-13).
  3. Fill standard product fields (name, category, tier, volume, price).
  4. Save → row in `products` with `barcode` column populated.
  5. Repeat. Expected total entries: 30–80 SKUs.

**Critical UX rule:** Mode A's primary input path is *typed barcode*.
Camera scan is a convenience, not the spine. Eliminates camera
reliability from the registry-build phase.

### Mode B — Arrival Scan (live event, must-work)

**Who:** Manager at each bar.
**When:** Whenever stock physically arrives at the bar (start-of-event
delivery + mid-event restocks from warehouse).
**Where:** Phone, on the bar, in motion.

**Workflow:**
  1. Open `/scan/arrivals` page (auto-scoped to manager's `assignedBarId`).
  2. Phone camera reads barcode (~1 sec).
  3. App looks up product in **locally cached registry** (instant, offline).
  4. If found: shows "Bacardi Rum 1L — tap to confirm" + audio beep.
  5. Tap → posts `stock_transactions` row of source `scan_arrival`,
     bar's `current_qty` increments by 1.
  6. If unknown: hard reject — sound + "Tell Owner to register this
     barcode in Catalog."

**Critical UX rule:** One bottle = one tap, < 2 seconds total. Two
scans of the same barcode within 3 seconds are deduped client-side.
Server-side dedup by `client_event_id` UUID.

### Mode C — Empty Reconciliation (post-event, stretch goal)

**Who:** Designated bartender or manager at each bar.
**When:** After event ends, before bar tear-down. ~30–60 min per bar.
**Where:** Phone, standing over a recycling bin of empties.

**Workflow:**
  1. Open `/scan/reconciliation` page (auto-scoped to user's bar).
  2. Continuous scan mode — point at empty, beep, move to next.
  3. Running counter: "37 empties scanned."
  4. Tap "Submit" when bin is empty.
  5. Backend computes per-product shrinkage:
     `arrivals (Mode B) − empties (Mode C) = unaccounted_for`
  6. Reconciliation report lands in event's post-event archive.

**Why post-event and not real-time during-event:**
Asking bartenders to scan empties during a live rush is the #1 way to
break their pour rhythm and create chaos. Post-event is calm,
methodical, batch. Data quality is identical. Capturing every empty
including ones broken mid-rush is only possible at the end.

---

## 3. Crash-risk strategy

The single biggest risk during Sundance is a scanner that fails
silently or freezes the bar workflow. Three principles mitigate:

### 3.1 Manual fallback is always one tap away

Every scanner page has a typed-barcode input visible at the top of
the screen. If the camera fails, glares, runs out of battery, denied
permission, or just feels slow — the operator types 13 digits and
proceeds. **This single decision removes scanner reliability from
the critical path.**

### 3.2 Registry is cached locally; scanner works offline

On scanner-page load, the entire barcode → product registry is
fetched once (small — < 100 rows, < 50KB) and cached in `localStorage`.
Every barcode lookup is instant and offline. Network is only needed
to *post* scan events, never to look up products.

### 3.3 Every scan is idempotent and queueable

Each scan generates a `client_event_id` UUID locally before any
network call. POSTs to `/stock-transactions`. If the POST fails
(network, backend slow, anything), the event sits in a `localStorage`
queue with a visible "X unsynced — retry" badge. Operator keeps
scanning; queue drains in background. Server dedupes by
`client_event_id`. **No scan is ever lost; no scan is ever counted twice.**

### 3.4 Explicit non-goals (what we are NOT building for Sundance)

  - Native iOS/Android apps. PWA + browser camera is good enough.
  - Multi-bottle-in-one-frame batch scanning.
  - Computer-vision product recognition without barcode.
  - Pour-volume estimation. Mode B = +1 bottle, Mode C = +1 empty.
  - Inventory write conflicts UI. Idempotency handles it server-side.
  - Mode A integrated into the scanner page. It lives in Catalog.

---

## 4. Data model

### 4.1 New column on `products`

```sql
---

## 6. Build plan

| Step  | Scope                                                                                                            | Risk    | ~Time  |
|-------|------------------------------------------------------------------------------------------------------------------|---------|--------|
| 6.1   | Backend: `barcode` column migration + `GET /by-barcode` + 3 enum values                                          | low     | 45 min |
| 6.2   | Frontend: Catalog product create/edit form gets barcode field (Mode A)                                           | low     | 60 min |
| 6.3   | Frontend: shared `<BarcodeScanner>` component (html5-qrcode + manual-entry + audio/haptic feedback)              | medium  | 2 hr   |
| 6.4   | Frontend: `/scan/arrivals` page (Mode B) — local cache, optimistic UI, idempotent POST queue, unsynced badge     | medium  | 3 hr   |
| 6.5   | Sidebar: restore "Scan Bottle" entry for Bartender + Manager                                                     | trivial | 5 min  |
| 6.6   | Browser-verify Mode A + B end-to-end with real device camera                                                     | n/a     | 30 min |
| 6.7   | (Stretch) Frontend: `/scan/reconciliation` page (Mode C) — batch empties scan, submit reconciliation             | medium  | 2 hr   |
| 6.8   | (Stretch) Backend: `GET /events/{id}/reconciliation-report` — arrivals vs empties per product per bar            | low     | 1 hr   |

**Sundance must-haves: 6.1 → 6.6** (~7 hours, 2 sessions).
**Stretch: 6.7 + 6.8** (~3 hours, 1 session).

If 6.1–6.6 ship and we run out of time, we still have a working
scanner system that solves the primary problem. 6.7+6.8 add the data
inference layer on top.

---

## 7. Sundance day-of "kill switch"

If the scanner is buggy on the day of Sundance, every operation is
recoverable through the existing UI:

  - Manager can manually allocate stock via existing Bars → Stock UI
    (`POST /api/v1/bar-stock/allocate`)
  - Manager can manually record consumption via existing Stock
    Transactions UI
  - Reconciliation can be done by hand with paper at end of event,
    entered after the fact

The scanner is a layer of speed and accuracy on top of an already-
working manual system. **It is not load-bearing.**

---

## 8. Library choice

`html5-qrcode` v2.x — MIT, ~80KB, supports EAN-13/EAN-8/UPC-A/
UPC-E/Code-128/QR. Active maintenance. Mobile camera reliable on
iOS Safari 14+ and Chrome Android 80+. Manual entry fallback always
present so library reliability is not load-bearing.

