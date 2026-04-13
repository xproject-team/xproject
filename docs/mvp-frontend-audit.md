# XProject Frontend Audit — MVP v2.1 Alignment

**Date:** 2026-04-13
**Auditor:** Hesam (with Claude)
**Goal:** Page-by-page comparison of current frontend vs. MVP v2.1 spec.
**Output:** Concrete edit list per page, to be executed in follow-up coding sessions.

---

## Page 1 — Login  ✅ AUDITED

**Current state:** Dev-mode 4-role selector (Owner / Manager / Warehouse Staff / Bartender). Click role → auto-signed in. No email, no password.

**MVP v2.1 requirement:** JWT auth with email + password, role from backend.

**Decision:** Accept as-is for the April demo.

**Rationale:**
- Real auth is being replaced by Clerk in week 2+ (post-Sundance).
- Demo priority is operational intelligence, not auth UX.
- Dev-mode screen is actually demo-friendly (one click → in).

**Post-demo TODO:**
- Replace with traditional email+password form backed by POST /api/v1/auth/login.
- Style preference: 4 seed accounts as selectable cards (click → auto-fills credentials).
- Integrate Clerk SSO when credentials arrive.

**Changes today:** None.

---


## Page 2 — Dashboard  ✅ AUDITED

**Current state:** Owner Dashboard showing Sundance 2026 LIVE event with KPI strip (Revenue, Drinks Sold w/ B/S/P/U tiers, Active Alerts, Time Elapsed, Warehouse Stock), Bar Performance grid (4 bar cards with Burn Rate/Depletion/Stock/Staff), and Alerts sidebar on the right. All data is mock.

**MVP v2.1 requirement:** Real-time operational view for Owner with live metrics, bar health monitoring, alerts feed, and v2.1 additions (Consumables, Food Truck, Weather, P&L, Briefing).

### Changes decided

**1. Tier labels — make them human-readable**
- Current: `B:142  S:152  P:130  U:63`
- Target:  `Basic 142 · Standard 152 · Premium 130 · Ultra 63`
- Rationale: letters are cryptic with no legend; full words improve glanceability.
- MVP status: ✅ compliant.

**2. Remove "Warehouse Stock 78%" tile from KPI strip**
- Rationale: Owner rarely acts on warehouse-level stock during a live event; not in MVP KPI scope.
- MVP status: ✅ compliant.

**3. Full card background tint by health status**
- Target: full card background tinted green/yellow/red based on BarStatus
- Rationale: bolder demo look; faster critical-state recognition.
- MVP status: ✅ compliant.

### MVP v2.1 additions to include

**4. Consumables Bar (HIGH)** — cups + ice tracking card/row. Source: Slesh prodotti.
**5. Food Truck Card (HIGH)** — alongside bar cards. Source: Slesh ordini filtered.
**6. Weather Pill (MEDIUM)** — current weather + forecast. Source: Open-Meteo API.

### Deferred to v1.1

**7. Event P&L preview** — requires wholesale cost + staff rate data.
**8. Briefing Sheet preview** — requires XHR staff-shift data.

### Backend work required for real data

Burn Rate calculation, Depletion formula, Alert engine, Slesh ingestion pipeline, Open-Meteo integration.

---


## Page 3 — Bar Detail (pop-up from Dashboard)  ✅ AUDITED

**Current state:** Side-panel overlay opens when clicking a bar card on the Dashboard. Shows: Revenue chart (actual vs ML predicted), Drinks Breakdown by tier, Stock table (6 products), Consumption vs Expected comparison, Alerts (3 items), Chat panel (1 message).

**MVP v2.1 requirement:** Owner drill-down view per bar with full inventory, real-time metrics, anomaly flags (Owner-only), bar-scoped chat, and restock request.

### Changes decided

**1. Stock column format — simplify**
- Current: `8/24`
- Target: `8 left (33%)` with unit ("bottles"/"liters"/"cases") in a tooltip on hover
- Rationale: denser, more glanceable; unit only surfaces when needed; Omar acts on "how much left" not "started with".
- MVP status: ✅ compliant.

**2. Remove "Consumption vs Expected" section entirely**
- Current: bar-chart list with "Anomaly detected" flags on every product (meaningless when everything is flagged)
- Target: delete the section from this view
- Alternative: anomalies surface exclusively in the Alerts list below (one source of truth)
- Rationale: duplication with Alerts, visually noisy, unclear action. Anomaly detection stays as an MVP feature — but as alerts, not as a redundant comparison chart.
- MVP status: ✅ compliant (anomaly flags stay; UI treatment changes).

**3. Depletion time — v1.0 rigor**
- Formula: `depletion_time = current_stock / rolling_20min_burn_rate`
- Display: single number (e.g. "3h 12m"), no confidence bands for v1.0
- Confidence bands / uncertainty ranges: deferred to v1.1
- Rationale: ship an accurate-enough simple number; layer sophistication later.
- MVP status: ✅ compliant (MVP requires depletion alert at 45-min threshold; this formula supports it).

### Bug identified

**4. Status badge logic mismatch**
- Current: Lime Juice shows "Warning" despite 3h 12m depletion (should be "Healthy" per MVP)
- MVP rule: Healthy (>2h), Warning (45min-2h), Critical (<45min), Depleted (0), Anomaly (pattern flag)
- Action: re-check frontend status threshold logic against MVP spec during execution phase
- MVP status: 🐛 bug (logic is wrong vs spec)

### Keep as-is (confirmed good)

**5. Revenue chart (Actual vs ML Predicted)** — keeps ML narrative, Omar-friendly
**6. Drinks Breakdown by tier** — Basic/Standard/Premium/Upgrade counts with percentages
**7. Alerts section** — clean, useful; user loved it

### MVP v2.1 additions to include

**8. Acknowledgeable alerts from pop-up**
- Current: only "Acknowledge" button shown on dashboard right sidebar
- Target: same Acknowledge button in the per-bar alerts section
- Rationale: Owner is already looking at the bar; don't force context-switch to sidebar
- Backend endpoint: `POST /events/{eid}/alerts/{aid}/ack` (already specified in Backend Bible)

**9. Full bar-scoped chat panel (Owner ↔ Manager)**
- Current: single static message
- Target: scrollable message history, input field + send, manager name + online indicator
- Also: unread-count badge on the bar card (on Dashboard grid) when new manager messages arrive
- Backend endpoints: `POST /events/{eid}/bars/{bid}/messages`, `GET /events/{eid}/bars/{bid}/messages` (already in Backend Bible)
- Rationale: MVP-required; Omar confirmed bar-scoped (not global) chat

**10. Restock Request action**
- Missing entirely
- Target: "Request Restock" button (visible to both Owner and Manager)
- Backend endpoint: `POST /events/{eid}/bars/{bid}/restock` (in Backend Bible)
- Rationale: MVP-required operational action

### MVP v2.1 additions to include (cross-cut with Dashboard)

**11. Consumables breakdown per bar** (cups/ice tracked separately from bottle stock)
**12. P&L preview per bar** — revenue − staff cost − inventory cost (deferred to v1.1)

### Role-permission rule (CRITICAL for execution)

**13. Anomaly alerts must be Owner-only**
- Owner view: anomaly alerts visible
- Manager view (same bar): anomaly alerts HIDDEN
- Enforcement: backend API must filter by role; frontend must also hide
- Rationale: Omar explicitly requested; revealing anomaly detection to managers breaks the trust model

### Data origin summary

| Metric | Source | Status |
|---|---|---|
| Revenue actual | Slesh `ordini` | In Excel, not loaded |
| Revenue ML-predicted | Prediction engine output | Backend work — not built |
| Drinks by tier | Slesh `prodotti` + `ordini` | In Excel, needs join |
| Stock per product | Slesh opening stock + `ordini` delta | Mixed source |
| Burn rate per product | Rolling 20-min window calc | Backend work — not built |
| Depletion per product | current_stock ÷ burn_rate | Backend formula — not built |
| Status badge | Derived from depletion + anomaly flags | Backend logic — not built |
| Alerts | Backend alert engine | Backend work — not built |
| Anomaly flags | ML anomaly detector (6 types per Backend Bible) | Backend work — not built |
| Chat messages | Chat module DB table | Backend work — not built |

**Conclusion:** Bar Detail is visually ~70% complete but requires substantial backend work: (a) Slesh ingestion, (b) ML prediction engine, (c) burn-rate calculation, (d) anomaly detector, (e) chat module, (f) restock module, (g) role-based permission filtering.

---


## Page 4 — Events list  ✅ AUDITED

**Current state:** Flat table of 4 mock events (Sundance 2026 Live, Summer Gala Draft, NYE Party Draft, Spring Festival Completed). Columns: Name, Date, Status, Guests, Bars, Venue, Actions (View/Edit).

**MVP v2.1 requirement:** List of all events with status-based actions and navigation to Event Detail.

### Changes decided

**1. Status tabs: `All | Live | Draft | Completed`**
- Target: tab control at top of page, default "All", click tab to filter
- Rationale: cleaner than scrolling through mixed statuses; matches Omar's mental model of "what's happening now vs what needs prep vs what's done"
- MVP status: ✅ compliant (MVP doesn't mandate tabs but lifecycle is explicit — tabs surface it)

**2. Actions column respects lifecycle**
- Draft: `Edit` + `Delete` + `Activate`
- Active: `View` + limited edits
- Live: `View` + `View Dashboard` (NO Edit, NO config changes)
- Completed: `View Report` (PDF) — no edits
- Rationale: MVP explicitly one-way lifecycle. Editing a Live event would corrupt ongoing operations.
- MVP status: ✅ compliant

### Bugs confirmed

**3. Edit button shown on Live events** — hide when status = Live/Completed
**4. No "+ Create Event" success navigation** — after Save Draft, should navigate to /events with toast confirmation

### Data origin
- Events list: `GET /api/v1/events` (already built in Phase 5) — fully functional endpoint
- Per-event status transitions: requires backend `POST /events/{eid}/activate`, `POST /events/{eid}/end` — not built yet

---

## Page 5 — Event Create  ✅ AUDITED

**Current state:** 5-section expandable form: Event Details, Bar Configuration, Menu Configuration, Recipes, Initial Stock Allocation. Save Draft button.

**MVP v2.1 requirement:** 5 config sections per the Event Lifecycle State Machine — all required before event can transition Draft → Active.

### Changes decided

**1. Section 1 (Event Details) — keep as-is** ✅
Standard event metadata. Works well.

**2. Section 2 (Bar Configuration) — keep as-is** ✅
Dynamic add/remove bars. Works well.

**3. Section 3 (Menu Configuration) — keep drink-only, add Food Truck as separate section**
- Keep: product name, category, tier (B/S/P/U), price — for drinks only
- New: Section 3b — "Food Truck Configuration" (separate block)
  - Food truck operator name, menu items, prices, revenue share %
- Rationale: Omar v2.1 explicitly requested Food Truck as separate module. Food trucks have different operators, analytics, revenue tracking.
- MVP status: ✅ compliant with v2.1 spec

**4. Section 4 (Recipes) — keep, improve labeling**
- Current: unclear purpose; confusing to new users
- Target: add section header help text: *"Define how each drink consumes stock. Required for accurate depletion tracking. Example: G&T uses 50ml gin from a 700ml bottle = 14 drinks per bottle."*
- Rationale: recipes are the MVP's intelligence foundation — every burn rate, depletion time, stock calculation depends on this conversion formula. Cannot remove. Just needs UX love.
- MVP status: ✅ critical MVP component

**5. Section 5 (Initial Stock Allocation) — keep, improve labeling**
- Current: unclear purpose
- Target: add section header help text: *"How many units of each product does each bar start the event with? Warehouse tracks total stock, bars track allocation — Owner needs to know per-bar levels."*
- Rationale: same as Recipes — MVP-critical. Without this, the depletion per bar cannot be computed. The UX problem is pedagogy, not the feature itself.
- MVP status: ✅ critical MVP component

### Bugs confirmed

**6. Save Draft doesn't navigate back to Events list** — should redirect to /events + show toast "Draft saved"

### MVP v2.1 additions

**7. Food Truck Configuration (new section)**
- Per decision #3 above, becomes its own config block
- Data: operator name, food items, prices, revenue-share % with Owner
- Backend: new model `FoodTruck`, endpoint `POST /events/{eid}/food-trucks`

### Data origin
- All 5 sections write to a single `events` row + related child tables (`bars`, `products`, `recipes`, `bar_inventory`) — Backend Bible specifies schema
- On Save Draft: single transaction writes event + children → status = "draft"
- On Activate: backend validates all 5 sections complete, sets status = "active"

---

## Page 6 — Event Detail (View)  ✅ AUDITED

**Current state:** Summary view of a single event. Shows: header (name + status + date + venue), 4 KPI cards (Bars, Expected Guests, Products, Venue), Event Details block, Bars table with per-bar status/staff/stock. Action buttons: Edit Event, View Dashboard, End Event.

**MVP v2.1 requirement:** Single-event drill-down with live data when status=Live, historical summary when status=Completed.

### Changes decided

**1. Status badge reflects actual event state**
- Current: "Live" badge shown for all events regardless of real status (bug)
- Target: badge matches `event.status` — "Draft" / "Active" / "Live" / "Completed" / "Cancelled"
- Rationale: misleading to show "Live" on a Completed event
- MVP status: 🐛 bug fix

**2. Live events auto-refresh every 10 minutes**
- Current: no refresh (static data)
- Target: when `status=Live`, poll data every 10 minutes (aligns with Slesh pipeline cycle)
- Rationale: MVP Data Pipeline Bible specifies 10-min refresh cycle. 2-minute poll would show stale data repeatedly.
- MVP status: ✅ compliant with Data Pipeline Bible

**3. Data sync with Dashboard (shared service layer)**
- Both pages must call the same backend endpoints for overlapping data (KPIs, bar list, bar statuses)
- No duplicate calculations in frontend
- Implementation note for execution phase: use shared `useEvents()` / `useEventSummary()` hooks, not separate queries
- MVP status: ✅ compliant

**4. Edit flow pre-fills existing values**
- Current: unclear if Edit opens blank form or shows current config
- Target: Edit button opens the Event Create form pre-populated with current values
- Same 5 sections, editable, Save to update (not Save Draft)
- Rationale: standard UX; starting blank would destroy existing config
- MVP status: ✅ compliant

**5. "End Event" with confirmation dialog**
- Current: button exists, likely one-click (dangerous)
- Target: click → modal dialog "This will end <event name>. Generate final report? [Cancel] [End Event]"
- After confirm: triggers final reconciliation, report generation, status transition Live → Completed, locks further edits
- Rationale: irreversible action; MVP has explicit one-way lifecycle — needs friction
- MVP status: ✅ compliant

**6. Action buttons respect status**
- Draft: Edit + Delete + Activate (no End Event, no View Dashboard — no live data)
- Active: Edit (limited) + View Dashboard + End Event
- Live: View Dashboard + End Event (no Edit — config locked)
- Completed: View Report only (no Edit, no End, no Dashboard — event is historical)
- Rationale: matches MVP lifecycle rules
- MVP status: ✅ compliant

### Keep as-is (confirmed good)

**7. 4 KPI summary cards** (Bars/Guests/Products/Venue) — clean, scannable
**8. Event Details block** — matches fields from Event Create
**9. Bars table with per-bar status** — good at-a-glance health check

### Data origin
- Event detail: `GET /api/v1/events/{id}` — needs to be built (only `GET /events` list exists from Phase 5)
- Per-bar status: requires burn-rate + depletion calculations (backend logic not built)
- Live refresh: polling on 10-min interval — implementation in useEventDetail hook
- Edit flow: `PATCH /api/v1/events/{id}` — not built
- End Event: `POST /api/v1/events/{id}/end` — not built, triggers report generation

---

