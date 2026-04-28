# XProject — Test Plans

**Status:** Living document · **Maintainer:** Hesam · **Last updated:** 2026-04-27

This is the single source of truth for manual testing of every shipped milestone.
After every milestone ships, its test plan is added here. Tests are run BEFORE
the milestone is considered "Sundance-ready."

When a test fails, the failure is logged inline with a date and a roadmap ref
(Tier 1 / Tier 2 / etc.) so it gets fixed in the right priority bucket — not
ignored, not auto-blocked.

---

## How to run a test plan

1. Pick the milestone section below.
2. Run each test in order. Each test has a clear pass condition.
3. Mark the result inline: ✅ pass / ⏳ pending / ❌ fail.
4. If ❌, write a one-line failure note + the date.
5. After all tests in a milestone show ✅, mark the milestone as
   **TESTED** at the top of its section with the date.

Failures get tracked here AND get a bug ticket added to docs/roadmap.md
under Tier 1 (if blocking) or Tier 2 (if non-blocking polish).

---

## Status legend

| Symbol | Meaning |
|---|---|
| ✅ | Test passed |
| ⏳ | Not yet tested (or partially tested) |
| ❌ | Test failed — see inline note |
| ⏭ | Skipped (test not applicable in current state, e.g. needs Slesh API) |

---

# Milestone — Bar Dashboard (Manager + Bartender)

**Status:** ⏳ pending final verification · **Spec:** docs/bar-dashboard-spec.md
**Sub-patches:** 3b.1 ✅ · 3b.2 ✅ · 3b.3 ✅ · 3b.4 ✅ · 3b.5 ✅ · 3b.6 ✅ · 3b.7 ⏳

## Test plan: BarDashboard-001 — Manager full path

**Pre-conditions:**
- Backend running on :8000, frontend on :5173
- M. Cocktail account exists with bar_id pointing at a bar in the LIVE event
- Cocktail Bar has bar_stock allocated and at least 5 transactions
- Cocktail Bar's chat channel exists with M. Cocktail as a member
- At least 1 critical alert exists for Cocktail Bar

**Tests:**

1. ⏳ Manager logs in via "M. Cocktail" pill → lands on /dashboard
2. ⏳ Header shows "Cocktail Bar" + "Sundance 2026 · Live event in progress"
3. ⏳ Live indicator top-right shows green dot + "live"
4. ⏳ Stock Health KPI shows a real % (not 0%, not placeholder)
5. ⏳ Revenue Tonight KPI shows a real € value (not 0€, not placeholder)
6. ⏳ Active Alerts KPI shows count >= 1 (red if any critical)
7. ⏳ Last 5 Transactions KPI shows count >= 1
8. ⏳ Active Alerts panel shows the critical alert with Acknowledge button
9. ⏳ Bar Chat panel shows recent messages + input + Send + Restock buttons
10. ⏳ Last 5 Transactions table shows real rows with timestamps + qty + source
11. ⏳ Footer links work: /inventory, /alerts, /chat
12. ⏳ Click Acknowledge on alert → button disappears, alert marked read
13. ⏳ Type message + click Send → message appears in chat panel
14. ⏳ Click Restock Request → templated message posted to chat

## Test plan: BarDashboard-002 — Cross-page sync

**Pre-conditions:** BarDashboard-001 passes

**Tests:**

1. ⏳ Send "test A" from dashboard chat panel → message appears
2. ⏳ Click "Open full chat →" → /chat opens with Cocktail Bar channel selected
3. ⏳ "test A" message visible on /chat page
4. ⏳ Send "test B" from /chat page
5. ⏳ Navigate back to /dashboard via sidebar → both messages visible in dashboard chat panel
6. ⏳ Open second browser tab at /dashboard
7. ⏳ Send "test C" from tab 1's dashboard chat
8. ⏳ Tab 2 shows "test C" within ~1s WITHOUT manual refresh (proves WebSocket push)

## Test plan: BarDashboard-003 — Bartender role

**Pre-conditions:** A bartender user exists with bar_id at the same bar

**Tests:**

1. ⏳ Bartender logs in → lands on /dashboard
2. ⏳ Header shows the assigned bar name (NOT "My Bar" placeholder)
3. ⏳ All 4 KPI tiles render with real numbers
4. ⏳ Active Alerts panel shows alerts BUT NO Acknowledge button (read-only)
5. ⏳ Bar Chat panel shows messages BUT NO input/Send/Restock (read-only)
6. ⏳ Sidebar does NOT show "Alerts" entry (Bartender doesn't have alerts page)
7. ⏳ Footer link "Full alerts page" is NOT visible

## Test plan: BarDashboard-004 — Owner role unchanged

**Pre-conditions:** Omar account

**Tests:**

1. ⏳ Omar logs in → lands on /dashboard
2. ⏳ Sees ALL bars (multi-bar overview, not "My Bar" view)
3. ⏳ No regression vs the dashboard he had before this milestone

## Test plan: BarDashboard-005 — Server-side bar-scoping

**Pre-conditions:** M. Cocktail logged in via curl to grab a JWT

**Tests:**

1. ⏳ Manager queries OWN bar_id → 200 with data
2. ⏳ Manager queries OTHER bar_id → 403 with "bar_access_denied"
3. ⏳ Manager queries with no bar_id → 200 (auto-fills to own bar)

---

# Milestone — Auth & Login

**Status:** ⏳ pending final verification · **Spec:** docs/auth-and-roles-spec.md

## Test plan: Auth-001 — Login form crash safety

**Tests:**

1. ⏳ Submit form with both fields empty → no blank page, native validation kicks in
2. ⏳ Submit valid email + WRONG password → red error banner appears AND STAYS (no page reload)
3. ⏳ Submit valid email + correct password → lands on role-appropriate landing
4. ⏳ Backend down (kill uvicorn) → "Can't reach the server" message, no crash
5. ⏳ Click "Forgot password?" → inert message (deferred per spec)

## Test plan: Auth-002 — Role-aware redirect

**Tests:**

1. ⏳ Owner login → lands on /dashboard
2. ⏳ Manager login → lands on /dashboard (filtered to own bar)
3. ⏳ Bartender login → lands on /dashboard (own bar view)
4. ⏳ Warehouse keeper login → lands on /warehouse

## Test plan: Auth-003 — Permission matrix enforcement

**Tests:**

1. ⏳ Manager hard-refreshes /events → redirects (Manager not allowed)
2. ⏳ Manager hard-refreshes /warehouse → redirects
3. ⏳ Manager hard-refreshes /predictions → redirects
4. ⏳ Bartender hard-refreshes /events → redirects
5. ⏳ Bartender hard-refreshes /alerts → redirects
6. ⏳ Warehouse keeper hard-refreshes /chat → redirects
7. ⏳ All roles can reach /settings

---

# Milestone — Reports

**Status:** ⏳ pending final verification · **Spec:** docs/report-module-spec.md

## Test plan: Reports-001 — Auto-trigger after event ends

**Pre-conditions:** An event in COMPLETED state with ended_at older than 15 min

**Tests:**

1. ⏳ arq cron runs the report-generation job within 5 min of cron tick
2. ⏳ Report row created in DB with status='ready'
3. ⏳ PDF generated and stored
4. ⏳ Italian + English narratives both render

## Test plan: Reports-002 — Frontend rendering

**Tests:**

1. ⏳ /reports list page shows ready reports
2. ⏳ Click a report → /reports/:id renders narrative + KPIs + PDF embed
3. ⏳ Language toggle switches narrative between IT and EN
4. ⏳ PDF download link works

---

# Milestone — Predictions

**Status:** ⏳ pending final verification · **Spec:** docs/predictions-module-spec.md

## Test plan: Predictions-001 — Three honest states

**Tests:**

1. ⏳ Empty DB → "Insufficient data" state shown, NOT fake numbers
2. ⏳ With historical events → "Ready" state with confidence bands
3. ⏳ After Owner edits expected_guest_count → auto-regen fires
4. ⏳ Generated prediction shows revenue, stock, staffing forecasts

---

# Milestone — Warehouse

**Status:** ⏳ pending final verification · **Spec:** docs/warehouse-module-spec.md

## Test plan: Warehouse-001 — Invoice scan flow

**Pre-conditions:** Warehouse keeper account exists, supplier invoice ready

**Tests:**

1. ⏳ Create new invoice from /warehouse/scan → state EXPECTED
2. ⏳ Click "Start scanning" → state SCANNING
3. ⏳ Scan items via camera (or manual fallback) → counts increment
4. ⏳ Pause → state PAUSED, scans preserved
5. ⏳ Resume → state SCANNING, can keep scanning
6. ⏳ Close → state VERIFIED if all match, DISCREPANCY if not
7. ⏳ DiscrepancyReport shows missing/extra items correctly

## Test plan: Warehouse-002 — 48h auto-close

**Pre-conditions:** A PAUSED invoice with scan_started_at older than 48h

**Tests:**

1. ⏳ arq cron runs cron_close_paused_invoices within 5 min
2. ⏳ Invoice transitions PAUSED → DISCREPANCY (or VERIFIED if scans match)
3. ⏳ closed_by is null (system-closed)

## Test plan: Warehouse-003 — Pending review queue

**Tests:**

1. ⏳ Owner sees /warehouse/pending-review with action buttons
2. ⏳ Warehouse keeper sees the page but NO action buttons
3. ⏳ Owner clicks Approve → row removed from queue
4. ⏳ Owner clicks Reject → row removed from queue

---

# Milestone — Settings

**Status:** ⏳ pending verification

## Test plan: Settings-001 — All roles can sign out

**Tests:**

1. ⏳ Owner → /settings → click Sign out → redirected to /login
2. ⏳ Manager → /settings → click Sign out → redirected to /login
3. ⏳ Bartender → /settings → click Sign out → redirected to /login
4. ⏳ Warehouse keeper → /settings → click Sign out → redirected to /login

---

# Failure log

(empty — no failures recorded yet)

---

# Document history

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-27 | Initial test plan compilation. Covers Bar Dashboard, Auth, Reports, Predictions, Warehouse, Settings milestones. |
