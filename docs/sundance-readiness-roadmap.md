# XProject — Sundance Readiness Roadmap

> **Living document.** This is the master reference for everything between today and Sundance go-live. Every phase has checkboxes. Every completed item gets a date and commit hash. When you don't know where you are, look at the **Status Pointer** below.
>
> **Last updated:** 2026-05-06 · **Owner:** Hesam · **Status:** v1.0

---

## 🧭 Status Pointer (UPDATE AS YOU GO)

**Phase:** 1 — Login redesign + multi-role auth foundation
**Current step:** ⏳ Not started — recon complete (2026-05-06), ready to begin Step 1.1
**Branch:** `develop` (will switch to `feat/auth-multirole-login` at Step 1.1)
**Last update:** 2026-05-06
**Days to Sundance:** ~35 (June 2026 target)
**Blockers:** None

> **How to update this section:** When you start a phase, change "Not started" to "In progress." When a phase finishes, update Phase to the next number. Keep it short — this is the dashboard, not the log.

---

## 📋 The 9 Phases at a Glance

| # | Phase | Focus | Risk | Estimate | Status |
|---|---|---|---|---|---|
| **0** | Recon | Read the codebase reality | None | 30 min | ✅ Done 2026-05-06 |
| **1** | Login + multi-role auth | Two-step login, `user_roles` join table, JWT role claim, session-expiry modal, profile-pic dropdown | Medium | ~3 days | 🔵 Next |
| **2** | Owner experience | Audit + complete every Owner page; deferred items (Inventory, Warehouse, Predictions, Reports, Page C, anomaly detectors, post-event report) | High | ~2 weeks | ⏸ |
| **3** | Manager experience | Audit + complete Manager's 5 pages | Medium | ~5–6 days | ⏸ |
| **4** | Bartender experience | Audit + complete Bartender's pages (excluding scanner) | Medium | ~5 days | ⏸ |
| **5** | Warehouse Staff experience | Audit + complete Warehouse pages (excluding scanner) | Low | ~2–3 days | ⏸ |
| **6** | Camera scanner system | Bottle scan + goods scan; camera permission, barcode decoding, offline queue | High | ~5–6 days | ⏸ |
| **7** | Cross-role bug-hunt | Systematic test every flow as every role; fix bugs one by one | Medium | ~4–5 days | ⏸ |
| **8** | Sundance dress rehearsal | Full simulated event, all 4 roles logged in simultaneously | Low | ~2–3 days | ⏸ |
| **9** | ML Model A | Demand forecasting | High | Whatever remains | ⏸ |

**Status legend:** 🔵 Next · 🟢 In progress · ✅ Done · ⏸ Pending · ⚠️ Blocked · ❌ Reverted

**Total realistic estimate:** ~5 weeks of focused work. Sundance June 2026.

---

## 🎯 The UX Standard (applies to every phase, every page)

A page is **not done** until all eight criteria pass:

1. **Logical button destinations** — every button goes where the user expects, no surprises (no "click avatar → logout").
2. **Consistent form validation** — required fields marked, errors shown inline, submission disabled until valid.
3. **Three states defined** — loading, empty, error — every page surfaces all three.
4. **Backend wired** — no mock data leaking through; if the UI shows it, the API returns it.
5. **Predictable click targets** — clicking a row opens detail; clicking a button performs an action; nothing else.
6. **Keyboard navigation** — Tab order makes sense, Esc closes modals, Enter submits forms.
7. **State persists across refresh** — refreshing the page lands the user back where they were.
8. **Role-correct** — only the role(s) intended see the page; others get a clean redirect.

**No exceptions.** A page that fails any criterion is incomplete and goes back into the queue.

> **What we are NOT doing:** visual redesign (theme, palette, typography). That happens after Sundance, in one pass, on top of a behavior-correct system.

---

## 🛡️ Standards Every Phase Must Meet

Before any phase is merged into `develop`, all five must be true:

- [ ] All existing tests still pass (no regressions)
- [ ] New code has its own tests (smoke + unit at minimum)
- [ ] Errors handled gracefully (no unhandled exceptions reach production)
- [ ] Logged at appropriate level (INFO for happy path, WARNING/ERROR for problems)
- [ ] Commit message follows conventional commits style (`feat(auth): ...`, `fix(ux): ...`, etc.)

**Branch hygiene:** one feature branch per phase. Squash-merge into `develop`. Delete the branch after merge.

---

## ⚠️ Sundance Readiness Lens

Every phase is held to one question: **"If Sundance happened tomorrow, does this code work safely with all four roles using the system simultaneously?"**

If the answer is "no" or "we'd have to apologize for X," the phase is not done.

---

# Phase 0 — Recon ✅ DONE (2026-05-06)

Verified the current state of the codebase.

**Findings:**
- 21 routes in `frontend/src/app/routes.tsx` (more than the sidebar shows; some are detail pages or hidden).
- Sidebar is role-aware with 4 distinct menus (Owner: 11 items, Manager: 5, Bartender: 5, Warehouse: 2).
- `Bars` and `Catalog` sidebar entries share the `bell` icon (small bug, fixed in Phase 1).
- TopBar avatar is **a logout button mislabeled as a profile picture** (lines 18, 24, 25 of `TopBar.tsx`). Fixed in Phase 1.
- User model has a single `role` column (`UserRole` enum, native Postgres). Phase 1 refactor: many-to-many via `user_roles` join table.
- Auth module is mature — `service.py`, `router.py`, `access_guards.py`, `schemas.py` already exist. Phase 1 is refactor, not build from zero.
- LoginForm is a dev-mode click-an-account selector with 5 hardcoded test accounts. Phase 1 replaces with proper two-step flow.
- Postgres enum `user_role` = `{OWNER, MANAGER, BARTENDER, WAREHOUSE}`. Stays as-is; `users.role` becomes a derived `users.active_role` plus a `user_roles` join table for assignment.

---

# Phase 1 — Login + Multi-Role Auth Foundation 🔵 NEXT

**Goal:** Replace the dev-mode 5-card LoginForm with a proper two-step login (role picker → credentials), refactor backend auth to support a user having multiple roles, and fix the TopBar profile-pic bug.

**Branch:** `feat/auth-multirole-login`

**Why first:** every downstream phase depends on auth being correct. Building features against broken auth means rebuilding permission checks later.

## Decisions locked

| # | Decision | Source |
|---|---|---|
| Q1 | Two-step login: role picker first, credentials second, back button supported | User decision |
| Q2 | Show only authorized roles for each user (a Manager-only user sees only "Manager") | User decision |
| Q3 | Session expiry → modal "Your session has expired" → redirect to credentials only (skip role picker, credentials remember last role) | Standard SaaS pattern |
| — | Multi-role schema: `user_roles` join table, JWT encodes the *active* role | System-design decision |
| — | TopBar avatar: dropdown with Profile / Switch Role / Sign Out (not click-to-logout) | UX standard |

## Sub-steps

### 1.1 — Branch + plan
- [ ] Create `feat/auth-multirole-login` from `develop`
- [ ] Read existing `app/modules/auth/` thoroughly; document current JWT shape

### 1.2 — Backend: many-to-many user roles
- [ ] Migration `p1_add_user_roles_table` — new `user_roles` join table (`user_id`, `role`, `assigned_at`, `assigned_by_user_id`)
- [ ] Backfill: every existing user gets one row in `user_roles` with their current `role`
- [ ] Keep `users.role` column for now as the "active role" field (will rename to `active_role` in 1.3 if needed)
- [ ] ORM: `User` gets `roles` relationship (list of UserRole)
- [ ] Repository: `get_user_authorized_roles(user_id) -> list[UserRole]`
- [ ] Tests: backfill correctness, multi-role assignment

### 1.3 — Backend: JWT + login endpoint
- [ ] `POST /auth/roles-for-email` — given an email (no password yet), returns the roles assigned to that user. Used by the role-picker step.
- [ ] `POST /auth/login` — accepts `(email, password, requested_role)`. Verifies role is in user's authorized set. Issues JWT with `active_role` claim.
- [ ] Existing `access_guards.py` reads `active_role` from JWT (was reading `role` from User table).
- [ ] Tests: auth with valid role, auth with unauthorized role (403), token refresh preserves active_role.

### 1.4 — Frontend: two-step login UI
- [ ] Step 1: Role picker — email input + "Continue" button → calls `/auth/roles-for-email` → shows role cards for which that user is authorized
- [ ] Step 2: Credentials — password input + "Sign In" button + Back button (returns to step 1, email preserved)
- [ ] Remove the 5 hardcoded account cards (move to a separate dev-mode helper component, gated by env flag)
- [ ] Validation: empty email → inline error; unknown email → inline error after step 1; wrong password → inline error on step 2
- [ ] Loading state: disable inputs + spinner on submit
- [ ] Error state: 401 → inline error; 5xx → toast
- [ ] Empty state: not applicable
- [ ] Keyboard: Enter advances step 1, Enter submits step 2, Esc clears errors
- [ ] State persistence: refresh on step 2 → stays on step 2 with email preserved

### 1.5 — Frontend: TopBar profile dropdown
- [ ] Replace single-click logout with dropdown menu
- [ ] Items: "Profile" (links to `/settings`), "Switch Role" (only if user has >1 role; reroutes to login step 1), "Sign Out" (logout + navigate to /login)
- [ ] Keyboard: Esc closes dropdown, Tab traverses items
- [ ] Click outside dropdown closes it

### 1.6 — Frontend: session expiry modal
- [ ] Axios interceptor catches 401 globally
- [ ] Shows modal: "Your session has expired. Please sign in again to continue."
- [ ] User clicks OK → save current path to `localStorage.lastPath` → navigate to login step 2 (skip role picker; remember last role from `localStorage.lastRole`)
- [ ] After successful re-login → restore `lastPath`

### 1.7 — Backend: assign-role endpoint (Owner-only)
- [ ] `POST /users/{user_id}/roles` — assign a role to a user (idempotent)
- [ ] `DELETE /users/{user_id}/roles/{role}` — revoke a role
- [ ] Owner-only access guard
- [ ] Tests

### 1.8 — Tests + commit
- [ ] All new tests passing
- [ ] All existing tests passing
- [ ] Manual browser test: log in as Omar (1 role), as a multi-role test user, verify session expiry, verify role-switch via TopBar dropdown
- [ ] Commit + PR + squash-merge to `develop`

**Phase 1 done when:** all 6 sub-steps checked, all 8 UX criteria pass on the login page and TopBar, all tests green, multi-role login verified end-to-end with at least 2 different role assignments.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 2 — Owner Experience ⏸

**Goal:** Audit and complete every page the Owner can access. This is the largest surface area.

**Branch:** `feat/owner-experience` (or split per page: `feat/owner-inventory`, `feat/owner-warehouse`, etc.)

**Owner sidebar (11 items):** Dashboard, Events, Bars, Catalog, Inventory, Alerts, Warehouse, Predictions, Reports, Chat, Settings.

## Per-page audit checklist (apply to all 11)

For each page:
- [ ] All 8 UX criteria pass
- [ ] All buttons go to the logical destination (no surprises)
- [ ] Backend wired (no mock data)
- [ ] Loading / empty / error states all defined
- [ ] Page accessible only to Owner role

## Sub-steps (in audit order — most-broken first)

### 2.1 — Dashboard (already wired) — UX audit pass
- [ ] Audit every interactive element (KPI tiles, BarCards, alert sidebar, top counters)
- [ ] Verify "polling stalled · 64h ago" UX is honest/useful (filed today)
- [ ] Verify quantity formatting (no "4530.000 piece"; render as "4530 pieces" or "4,530 pcs")
- [ ] Empty state: no event selected → meaningful message
- [ ] Error state: API down → graceful fallback

### 2.2 — Events list + Event Detail (Pages A + B exist; audit only)
- [ ] Re-verify against `docs/event-page-flow.md`
- [ ] Audit pass

### 2.3 — Events Page C (Create wizard) — backend wiring
- [ ] Verify all 6 sections wire to real backend endpoints
- [ ] Strict validation matches `docs/event-page-flow.md`
- [ ] Save Draft / Activate / Go Live transitions work end-to-end
- [ ] Audit pass

### 2.4 — Bars list + detail (Phase E shipped) — UX audit pass
- [ ] Fix shared icon bug (Bars and Catalog both use `bell`)
- [ ] Audit pass

### 2.5 — Catalog (Phase F shipped) — UX audit pass
- [ ] Audit pass

### 2.6 — Inventory page — wire + audit
- [ ] Discover current state (mock vs real)
- [ ] Wire to real backend if mocked
- [ ] Define states, audit pass

### 2.7 — Alerts page — UX audit pass
- [ ] Already wired; just audit
- [ ] Verify dual ANOMALY+CRITICAL pill rendering, owner-only filter, acknowledge flow

### 2.8 — Warehouse pages — wire + audit
- [ ] `/warehouse` — Owner overview
- [ ] `/warehouse/scan` — see Phase 6 (camera scanner system)
- [ ] `/warehouse/pending-review` — discover purpose, wire if mocked

### 2.9 — Predictions page — wire + audit
- [ ] Discover current state
- [ ] Wire to real backend (or note that it depends on Phase 9 ML)
- [ ] If ML-dependent, define a "no model yet" empty state

### 2.10 — Reports page — wire + audit
- [ ] Discover current state
- [ ] Implement post-event report generator (deferred item) — bilingual PDF: alert ledger + burn-rate history + revenue summary
- [ ] Wire `/reports/:reportId` to real backend
- [ ] Audit pass

### 2.11 — Chat page — UX audit pass
- [ ] Already wired; audit only
- [ ] Verify channel switching, message ordering, mark-read

### 2.12 — Settings page — wire + audit
- [ ] Discover current state
- [ ] Add: change password, profile info, view assigned roles
- [ ] Audit pass

### 2.13 — Anomaly detectors #3, #4, #5
- [ ] Detector #3: Consumption Ratio (drinks-sold vs stock-decremented)
- [ ] Detector #4: Demand Drop (inverse of Demand Spike)
- [ ] Detector #5: Missing Stock (stock unaccounted for)
- [ ] Each: detector class, register in `AlertsOrchestrator`, manual fire test, browser verification
- [ ] (Detector #6 — Warehouse Discrepancy — defer; needs barcode hardware)

### 2.14 — Tests + commit
- [ ] All tests green
- [ ] Manual browser test full Owner flow
- [ ] Commit + PR + squash-merge

**Phase 2 done when:** all 11 sidebar pages pass all 8 UX criteria, anomaly detectors 3–5 are firing, post-event report generates a real PDF, every page is wired to real backend.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 3 — Manager Experience ⏸

**Goal:** A complete, polished Manager experience. Designed as a Manager-first product, not as "Owner UI minus stuff."

**Branch:** `feat/manager-experience`

**Manager sidebar (5 items):** My Bar, Inventory, Alerts, Chat, Settings.

## Sub-steps

### 3.1 — My Bar (Manager dashboard) — design + implement
- [ ] Manager-first home: their bar's revenue, stock health, active alerts (depletion only — anomaly hidden), incoming chat, last 5 transactions
- [ ] Different from Owner Dashboard: scoped to one bar, no cross-bar comparison
- [ ] All 8 UX criteria

### 3.2 — Inventory (Manager view) — wire + audit
- [ ] Manager sees only their bar's inventory
- [ ] Restock request action wired to backend
- [ ] All 8 UX criteria

### 3.3 — Alerts (Manager view) — verify filter + audit
- [ ] Manager sees only depletion alerts for their bar (anomaly hidden — verified end-to-end during Phase F)
- [ ] All 8 UX criteria

### 3.4 — Chat (Manager view) — verify + audit
- [ ] Manager sees their bar's channel + DMs with Owner
- [ ] Auto-join hook (deferred item): when a Manager is assigned to a bar, they auto-join that bar's channel
- [ ] All 8 UX criteria

### 3.5 — Settings (Manager view) — wire + audit
- [ ] Same shape as Owner Settings, scoped to Manager-relevant items
- [ ] All 8 UX criteria

### 3.6 — `PATCH /bars/{id}/manager` UI (deferred item)
- [ ] Owner-side UI to assign/reassign managers to bars
- [ ] Auto-join hook fires correctly

### 3.7 — Tests + commit
- [ ] Manual browser test: log in as a Manager, walk every page, verify scoping
- [ ] Commit + PR + squash-merge

**Phase 3 done when:** all 5 Manager pages pass all 8 UX criteria, scoping is enforced end-to-end, auto-join hook works.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 4 — Bartender Experience ⏸

**Goal:** A complete Bartender experience. Mobile-friendly (Bartenders use tablets/phones at the bar). Scanner is excluded — that's Phase 6.

**Branch:** `feat/bartender-experience`

**Bartender sidebar (5 items):** My Bar, Inventory, Scan Bottle, Chat, Settings.

## Sub-steps

### 4.1 — My Bar (Bartender view) — design + implement
- [ ] Bartender-first home: today's drinks sold, current stock at-a-glance, last orders, basic communication
- [ ] Touch-friendly (tap targets ≥44px per HIG, even though we're not theming)
- [ ] All 8 UX criteria

### 4.2 — Inventory (Bartender view) — wire + audit
- [ ] Read-only view of their bar's stock
- [ ] All 8 UX criteria

### 4.3 — Scan Bottle (UI shell only — actual scanner in Phase 6) — placeholder + audit
- [ ] Page structure ready, scanner integration deferred
- [ ] Empty state: "Scanner ready — point camera at bottle barcode" (placeholder)

### 4.4 — Chat (Bartender view) — wire + audit
- [ ] Bartender sees their bar's channel
- [ ] All 8 UX criteria

### 4.5 — Settings (Bartender view) — wire + audit
- [ ] Same shape, scoped

### 4.6 — Tests + commit
- [ ] Manual browser test on tablet-sized viewport
- [ ] Commit + PR + squash-merge

**Phase 4 done when:** all 5 Bartender pages pass all 8 UX criteria, mobile/tablet viewports work cleanly. Scanner page has its UI shell ready for Phase 6.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 5 — Warehouse Staff Experience ⏸

**Goal:** A complete Warehouse Staff experience. Smallest surface but mobile-first.

**Branch:** `feat/warehouse-experience`

**Warehouse Staff sidebar (2 items):** Scan Goods, Settings.

## Sub-steps

### 5.1 — Scan Goods (UI shell only) — placeholder + audit
- [ ] Page structure ready, scanner integration in Phase 6
- [ ] List of pending dispatch tasks
- [ ] All 8 UX criteria for the list/list-empty/list-error states

### 5.2 — Settings (Warehouse view) — wire + audit
- [ ] All 8 UX criteria

### 5.3 — Tests + commit
- [ ] Manual browser test on phone-sized viewport (Warehouse Staff often use phones)
- [ ] Commit + PR + squash-merge

**Phase 5 done when:** both Warehouse pages pass all 8 UX criteria, mobile viewport works.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 6 — Camera Scanner System ⏸

**Goal:** Build the camera-based barcode scanner shared by Bartender (bottle scan) and Warehouse Staff (goods scan).

**Branch:** `feat/camera-scanner`

**Why its own phase:** scanner touches camera permission, barcode decoding, mobile constraints, offline queue, conflict resolution. Lumping it into per-role audits would short-change it.

## Sub-steps

### 6.1 — Library selection + spike
- [ ] Evaluate `@zxing/browser`, `quagga2`, `html5-qrcode`. Pick one based on accuracy + bundle size + maintenance.
- [ ] Build a 1-page spike: open camera, decode any barcode, log the result. Verify on iOS Safari, Android Chrome, desktop.

### 6.2 — Backend: scan endpoint
- [ ] `POST /scans` — accepts `(barcode, scan_type=BOTTLE_SCAN|GOODS_SCAN, bar_id?, batch_id?)`
- [ ] Idempotency: same barcode within 30s = single scan
- [ ] Returns: matched product (if found), scan record id, alert if discrepancy

### 6.3 — Frontend: scanner component
- [ ] `<BarcodeScanner onScan={...} />` — handles camera permission UX, decoding, error states
- [ ] Three states: requesting permission, scanning, error (no camera / permission denied)
- [ ] Manual entry fallback: text input for barcode if camera fails

### 6.4 — Bartender Scan Bottle integration
- [ ] Wire scanner to bottle-decrement workflow
- [ ] Confirmation modal: "You scanned X. Confirm consumption?"
- [ ] Optimistic UI; real backend call

### 6.5 — Warehouse Scan Goods integration
- [ ] Wire scanner to dispatch workflow
- [ ] Pending review queue if barcode not recognized
- [ ] All 8 UX criteria

### 6.6 — Offline queue
- [ ] If backend unreachable, queue scans in `localStorage`
- [ ] On reconnect, drain queue with idempotent re-submission

### 6.7 — Anomaly detector #6 — Warehouse Discrepancy
- [ ] Now possible because scans are happening
- [ ] Compare requested-quantity vs scanned-quantity per restock
- [ ] Register in `AlertsOrchestrator`

### 6.8 — Tests + commit
- [ ] Browser test on real iOS / Android devices
- [ ] Commit + PR + squash-merge

**Phase 6 done when:** Bartender can scan a bottle and see stock decrement; Warehouse Staff can scan goods during dispatch; offline queue drains correctly; Warehouse Discrepancy alerts fire.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 7 — Cross-Role Bug Hunt ⏸

**Goal:** Systematically test every flow as every role. Find every bug, fix one by one.

**Branch:** `feat/bug-hunt-pass-1` (rolling — keep merging)

## Method

For each role, walk every page and every flow. Log every bug to a shared list. Fix from highest-severity to lowest.

## Bug categories

- **Severity 1 (blocker):** crashes, data loss, security holes, role-leak (one role sees data they shouldn't)
- **Severity 2 (major):** broken workflows, misleading errors, lost state on refresh
- **Severity 3 (minor):** copy errors, alignment, cosmetic
- **Severity 4 (polish):** the visual-redesign pile (deferred to post-Sundance)

## Sub-steps

### 7.1 — Owner full walkthrough
### 7.2 — Manager full walkthrough
### 7.3 — Bartender full walkthrough
### 7.4 — Warehouse Staff full walkthrough
### 7.5 — Cross-role flows: Owner messages Manager, Manager acknowledges alert, Bartender scans bottle, Owner sees deduction, etc.
### 7.6 — Role-switching: log in as Owner, switch to Manager via TopBar dropdown, verify clean transition
### 7.7 — Session expiry: kill JWT, verify modal-then-credentials-only flow
### 7.8 — Fix all S1 bugs
### 7.9 — Fix all S2 bugs
### 7.10 — Fix S3 bugs as time allows
### 7.11 — Document remaining S3/S4 in `docs/known-issues.md`

**Phase 7 done when:** zero S1 bugs, zero S2 bugs, S3/S4 documented, all role walkthroughs clean.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 8 — Sundance Dress Rehearsal ⏸

**Goal:** Run a full simulated event with all four roles logged in simultaneously. Find what breaks under realistic load and concurrency.

**Branch:** `feat/dress-rehearsal-fixes`

## Sub-steps

### 8.1 — Setup
- [ ] Create test event "Sundance Dress Rehearsal 2026"
- [ ] Seed 3 bars, 4 managers, 6 bartenders, 2 warehouse staff
- [ ] Pre-load realistic stock + recipes from Sundance 2025 historical data

### 8.2 — Multi-role concurrent test
- [ ] 4 browser windows: Owner, Manager (Cocktail Bar), Bartender (Cocktail Bar), Warehouse Staff
- [ ] Run a 30-minute simulated event:
  - Slesh polling ingests fake order stream
  - Bartender scans bottles
  - Warehouse dispatches goods
  - Manager sees their bar's status update live
  - Owner sees aggregate live
  - Anomaly fires; Owner acknowledges silently; Manager sees neutral chat post

### 8.3 — Failure modes
- [ ] Backend goes down mid-event — graceful degradation
- [ ] Network slow — UI still responsive
- [ ] One role's session expires — modal works, others unaffected
- [ ] Two managers post chat simultaneously — no message loss

### 8.4 — Performance
- [ ] Dashboard loads in <3 seconds
- [ ] WebSocket reconnects in <5 seconds
- [ ] No memory leaks after 30 minutes

### 8.5 — Fix issues, retest
- [ ] Iterate until full 30-minute simulation passes cleanly

**Phase 8 done when:** full 30-minute multi-role simulation completes with zero S1/S2 issues. This is the Sundance go/no-go.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Phase 9 — ML Model A (Demand Forecasting) ⏸

**Goal:** Build the demand forecasting model. Last phase, after the platform is solid.

**Branch:** `feat/ml-model-a`

**Why last:** ML is exploratory. It needs a stable foundation under it (data pipeline, schema, weather feed all already shipped). Doing it last means it trains against a system that won't shift.

## Sub-steps (high-level — detailed plan written when this phase starts)

### 9.1 — Data audit
- [ ] Profile the Slesh historical orders we have ingested
- [ ] Join with weather (Open-Meteo already integrated)
- [ ] Identify gaps and biases

### 9.2 — Feature engineering
- [ ] Hour-of-event, weather, ticket-sales curve, expected guests, day-of-week, etc.
- [ ] Train/validation/test split

### 9.3 — Model selection
- [ ] Baseline: linear regression
- [ ] Candidates: gradient boosted trees, simple LSTM
- [ ] Pick based on accuracy + interpretability

### 9.4 — Backend integration
- [ ] Predictions endpoint `GET /predictions/by-event/{id}`
- [ ] Wire to Predictions page (Phase 2.9)

### 9.5 — Tests + commit
- [ ] Backtest accuracy targets
- [ ] Manual review of predictions vs ground truth
- [ ] Commit + PR + squash-merge

**Phase 9 done when:** Predictions page shows real model output; backtest accuracy meets target.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

# Appendix A — Items Explicitly Deferred to Post-Sundance

These items were considered for inclusion and explicitly pushed past Sundance go-live:

- **Visual theme redesign** — done in one pass after Sundance, on top of behavior-correct pages
- **Token rotation policy with Slesh** — operational, not code; calendar reminder for week-after-Sundance
- **Multi-tenant scaling** (cache + cursor logic for tenant isolation) — only matters when adding 2nd tenant
- **Event P&L preview** — needs wholesale cost data + staff rates Hesam doesn't have yet
- **Briefing Sheet preview** — needs XHR staff-shift data
- **B6.7–B6.14 polling worker formal pytest tests** — functionality verified manually with real data
- **Async test infrastructure rebuild** — the asyncpg "another operation in progress" issue
- **ORM mapper init bug** — `User` relationship in `alerts/models.py` breaks standalone scripts; production fine
- **Multi-language UI** — UI stays English; reports stay bilingual

---

# Appendix B — Memory Anchors (so we don't lose context)

Key facts for future sessions:

- `docs/event-page-flow.md` is the Events state-machine source of truth
- `docs/chat-module-spec.md` is the chat module spec (already implemented)
- `docs/slesh-integration-roadmap.md` is the Slesh integration tracker (complete)
- `docs/sundance-readiness-roadmap.md` (this file) is the master tracker from 2026-05-06 onward
- Sundance target: June 2026
- Owner test account: `omar@nomagroup.it` / `xproject2026`
- 5 seed accounts in `LoginForm.tsx` cover all 4 roles for testing
- The 4 Postgres user roles: OWNER, MANAGER, BARTENDER, WAREHOUSE
- Backend single-tenant currently (Noma Group only); multi-tenant scaling is post-Sundance
- Real Sundance 2025 historical data is in `stock_transactions` for testing/training
- Theme redesign is post-Sundance — do NOT touch colors/typography/spacing during Phases 1–8

---

**End of roadmap. v1.0. Living document. Update Status Pointer as you go.**
