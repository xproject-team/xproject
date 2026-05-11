# XProject Scanner — System Design

**Status:** Implemented 2026-05-11 — see §9
**Originally approved:** 2026-05-08
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


---

# PHASE 6 IMPLEMENTATION RECORD

**Implementation period:** 2026-05-09 to 2026-05-11
**Total commits on `develop`:** 19 sub-steps
**Verification:** 3-role browser-tested (Owner + Manager + Bartender), all PASS

The pre-build spec (§§1–8 above) described intent. This section records what actually shipped. Where reality diverged from spec, rationale is captured here so future readers know the WHY of every difference.

---

## §9. The 12 Sundance-Safety Principles

The pre-build spec called out three crash-mitigation principles. The implementation extended these to twelve, each named in code at the top of relevant files. Each is enforced by a specific mechanism, not just a guideline.

1. **Manual fallback always one tap** — Input always visible alongside camera, no toggle. `BottleScanCard.tsx`.
2. **Pre-scoped to operator's bar** — Page reads `assignedBarId`, renders guard if null. `BarScanArrivalsPage.tsx` L100-130.
3. **Pre-scoped to live event** — Page calls `useLiveEvent()`, renders guard if null. `BarScanArrivalsPage.tsx` L100-110.
4. **Idempotent every scan** — Client UUID + (tenant, UUID) unique index. `scanQueue.ts` + migration `r1`.
5. **Visible scan history** — Last-10 rows via `ScanHistoryRow`. `BarScanArrivalsPage.tsx` L150-180.
6. **Loud network failures** — `SyncIndicator` shows pending/failed counts. `BarScanArrivalsPage.tsx` L70-95.
7. **No destructive controls on scan pages** — Append-only history. Undo per-row, server-rolled. `ScanHistoryRow.tsx` L110-150.
8. **Audio + haptic + visual flash on result** — Two-of-three redundancy from `feedback.ts`.
9. **Audio primed on first user gesture** — `primeAudio()` inside permission-tap handler. `BottleScanCard.tsx` L155-170.
10. **Backend authoritative for permissions** — `_ROLE_SCAN_PERMISSIONS` matrix. `scan_service.py`.
11. **Kill switch documented** — Bars → Stock UI fallback path exists. See §7 above.
12. **Business-value signal** — Reconciliation report (Mode B - Mode C - POS sales). `reconciliation_service.py`.

**Defense-in-depth note:** principles #2, #3, and #10 together provide three independent enforcement layers for "Manager cannot DISPATCH at a bar they don't manage." See §11.

---

## §10. Reconciliation — what stretch goals 6.7+6.8 became

The pre-build spec listed 6.7 (frontend reconciliation) and 6.8 (backend reconciliation report) as STRETCH goals. Both shipped, but with a meaningfully different architecture than the spec implied.

**What the spec proposed (§2.C / §6.7-6.8):** "Continuous scan mode — point at empty, beep, move to next. Tap Submit when bin is empty. Backend computes per-product shrinkage: arrivals (Mode B) − empties (Mode C) = unaccounted_for."

**What we built:**

- **Mode C** is the same workflow but at the SAME UX shape as Mode B. Both pages reuse `BottleScanCard` and `ScanHistoryRow`; the only difference is the `scanType` prop (`DISPATCH` vs `CONSUMED`). The spec implied two different page designs; the build collapsed them into one component used twice. Rationale: rule-of-three discipline — don't extract a shared parent until you've seen the pattern three times.

- **The reconciliation report endpoint** (6.11) does NOT compute "unaccounted_for" at the per-(bar, product) row level. Why: `warehouse_allocations.dispatched_qty` lives at (event, product) granularity, not per-bar. The honest signal level is therefore "warehouse → event" totals, surfaced as an `EventProductGap` in the summary section of the response. Per-row data stays clean (arrived, consumed, net); gaps live in the summary where ground-truth aggregation supports them.

- **Three flag severities** (MINOR/MODERATE/MAJOR) tuned for Sundance pilot: gap_pct < 1% no flag (rounding noise), 1-5% MINOR, 5-15% MODERATE, ≥15% MAJOR. Plus the catastrophic pattern: dispatched > 0 AND arrived = 0 → always MAJOR (theft-in-transit or manager-didn't-scan-at-all), surfaced via a separate query with `NOT EXISTS`.

- **The Owner-facing viewer** (6.12) is reachable from `EventDetailPage` via a "View Reconciliation" button — Owner-only, visible when event status is `live` or `completed`. NOT in the sidebar; reconciliation is per-event, a sidebar entry would imply "which event?" which means a picker, which is noise.

---

## §11. Defense-in-depth — three independent permission layers

Each user action that should be permission-gated passes through three independent layers. Any one is sufficient. All three are present.

**Layer 1 — Frontend conditional render.** Examples: `effectiveCanViewReconciliation` in `EventDetailPage` hides the button entirely; `canScanArrivalsAtBar` in `Sidebar.tsx` hides the nav entry. If the user lacks permission, they never see the action exist.

**Layer 2 — Route guard.** `<RequirePermission flag="...">` in `routes.tsx`. On denial, dispatches a `permission:denied` CustomEvent (triggers the `PermissionDeniedToast`) and redirects to the role's home route. Catches direct-URL navigation attempts.

**Layer 3 — Backend role check.** Owner-only endpoints have `if user.role != UserRole.OWNER: raise HTTPException(403)`. Scan endpoints check `_ROLE_SCAN_PERMISSIONS` matrix. Every CTE in SQL filters on `tenant_id`. The boundary the system cannot lie about.

**Verified live in 6.12.4:** when Manager + Bartender hit the reconciliation URL directly, Layer 2 blocked them. DevTools Network confirmed the `/reconciliation-report` API call NEVER FIRED. The toast explained why. The backend was never consulted. Each layer is sufficient; all three are present.

---

## §12. Architecture decisions retrospective

Decisions made during build, with rationale captured for future code reviews.

**12.1 — Decimal-as-string for all quantities.** All numeric quantities (arrived_qty, consumed_qty, dispatched_qty, etc.) serialized as JSON strings, not numbers. Why: JS `Number` cannot represent some decimal values exactly (0.1L pour becomes 0.09999...). Strings preserve precision end-to-end. Cost: frontend cannot do arithmetic on these fields without explicit conversion; sort comparator is custom (`compareQty`). Worth it.

**12.2 — Single SQL query for the reconciliation report.** Main query + zero-arrival query both run in the SAME async session. Total 2 SQL roundtrips for the entire report. Why: multi-query reports during a live event have race conditions — if a DISPATCH lands between queries, numbers are internally inconsistent. One snapshot, internally consistent.

**12.3 — Copy-paste over abstraction for Mode B / Mode C.** `BarScanArrivalsPage` and `BarScanEmptiesPage` are near-identical (335 lines each, differing in 6 strings). Why: premature abstraction. Manager and Bartender have different jobs; the pages MAY diverge as we learn. Rule of three: don't extract until you've seen the pattern three times. Two pages = stay copy-pasted.

**12.4 — Append-to-file-end over regex-anchored injection.** New module-level code added by appending to end of file. Mid-file insertions via count-validated `str.replace`, never naive regex. Why: hard lesson from 2026-05-09. Regex injection into TypeScript files with type annotations (`Record<string, foo>{...}`) produced subtle `,,` typos that crashed import-time module loading. Cost ~30 min to debug. Lesson applied for every commit since.

**12.5 — `PermissionDeniedToast` mirrors `SessionExpiredModal`.** Cross-cutting permission-denial UX uses CustomEvent + single-mount global listener, same pattern as the existing session-expiry handler. Why: codebase consistency over framework novelty. The codebase already solves "global cross-cutting UX events" via CustomEvent. Adding a toast library to solve the same problem would be dependency creep.

**12.6 — Owner sidebar deliberately spare for scanner pages.** Owner has 11 sidebar entries; we did NOT add scanner or reconciliation entries. Owner accesses scanner pages via direct URL when testing, and reconciliation via `EventDetailPage`. Why: sidebar is the operator's daily-use menu. Owner is a business user, not a floor operator. 11 items > 13 items reduces wrong-tap risk under Sundance pressure.

**12.7 — Always-rendered Section 2 with 3 branches.** The "Delivery gaps" section in the reconciliation viewer always renders, in one of three branches: ✅ All clear / ⚠ Gaps found / ⏸ Not started. Why: reassurance deserves equal visual weight to alarm. A muted footer saying "no gaps detected" leaves Omar scrolling wondering. A green "All clear" card is binary and unambiguous.

---

## §13. What's deferred to Phase 7+

Items intentionally NOT shipped in Phase 6, with rationale for deferral.

- **Slesh POS integration** — sandbox credentials still pending from Omar. Reconciliation report shows `missing_pos_data: true` until this lands. The "sold via recipe vs arrived" and "over-pour variance" signals are designed but not wired.
- **Manager-scoped reconciliation report** — currently Owner-only. A Manager-scoped variant (sees only their bar's rows) would be a small extension to the 6.11 endpoint. Defer until Omar requests.
- **End-of-event physical inventory count** — no current workflow to capture "leftover stock at bar after event." Once shipped, the reconciliation report can compute true shrinkage: arrived - consumed - leftover.
- **Toast z-index polish** — `PermissionDeniedToast` overlaps the top-bar LIVE chip slightly. Readability unaffected.
- **favicon 404** — site-wide, cosmetic. Not scanner-specific.
- **React Router v7 future-flag warnings** — advisory library upgrade nudges. No behavior impact.
- **`RecipeCreatePage` unused-import warning** — pre-existing, from May 6 commit `d75456c9`.
- **Audio/haptic on physical device** — verified in code; cannot test via DevTools. Phase 6.14 dress rehearsal handles this.
- **Offline queue drain on simulated outage** — code path exists, never exercised during testing because all POSTs succeeded online. Phase 6.14 covers this with intentional API kill.

---

## §14. Commit log — Phase 6 sub-steps

Reference table for code archaeology. Each row maps to a single commit on `develop`.

- 6.1 `4b9daff` — backend barcode column
- 6.2 `c983ab6` — Catalog form (Mode A)
- 6.3 `311045f` — backend idempotency
- 6.4 `45df782` — frontend UUID + offline queue
- 6.5 `40c38c9` — permission flag split
- 6.6.0 `bbb1620` — backend undo for DISPATCH/CONSUMED
- 6.6.1a `dc48f77` — audio + haptic feedback primitives
- 6.6.1b `4a2a00e` — useVoidScan TanStack mutation
- 6.6.1c `3b2a97d` — ScanHistoryRow with 5s Undo countdown
- 6.6.1d `f9df9fc` — BottleScanCard with camera + manual + feedback
- 6.6.2 `345ec55` — BarScanArrivalsPage (Manager Mode B)
- 6.7 `40a82f9` — BarScanEmptiesPage (Bartender Mode C)
- 6.8 `6ce19a1` — scanner routes + sidebar wiring
- 6.9 — three-role browser verification PASS
- 6.9a `f17e43c` — PermissionDeniedToast on cross-role navigation
- 6.11 `1aecc0d` — reconciliation report endpoint (Owner only)
- 6.12.1 `2101fe5` — useReconciliationReport TanStack hook
- 6.12.2 `2f5e023` — EventReconciliationPage viewer
- 6.12.3 `c9176d5` — reconciliation route + button wiring
- 6.12.4 `5c4dc52` — three-role verification PASS
- 6.13 (this commit) — docs final pass

---

*End of Phase 6 Implementation Record. Pre-build narrative §§1–8 above preserved as design history.*
