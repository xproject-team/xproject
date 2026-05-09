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

**Why split into 4 sub-phases (1A → 1B → 1C → 1D):** recon on 2026-05-07 revealed `current_user.role` is read in 20 places across 9 files (chat, bars, alerts, warehouse, predictions, reports, auth). A single big-bang refactor of all 20 call sites at once is how production outages happen. The 4-sub-phase rollout uses the standard **expand/contract migration pattern**: each sub-phase has a working-system checkpoint, the system is functional at every intermediate step, and the 20 call sites get migrated last (1D) once the new contract is proven.

## Decisions locked

| # | Decision | Source |
|---|---|---|
| Q1 | Two-step login: role picker first, credentials second, back button supported | User decision |
| Q2 | Show only authorized roles for each user (a Manager-only user sees only "Manager") | User decision |
| Q3 | Session expiry → modal "Your session has expired" → redirect to credentials only (skip role picker, credentials remember last role) | Standard SaaS pattern |
| — | Multi-role schema: `user_roles` join table, JWT encodes the *active* role | System-design decision |
| — | TopBar avatar: dropdown with Profile / Switch Role / Sign Out (not click-to-logout) | UX standard |
| — | Rollout: 4-sub-phase expand/contract pattern (1A → 1B → 1C → 1D) | Recon 2026-05-07 |

## Recon findings (2026-05-07)

Documented in this section so future sessions don't re-discover them:

- **No prior multi-role work exists.** No `user_roles` table, no related migrations, no frontend hints, no stashes, no relevant work-in-progress branches. Phase 1 is greenfield.
- **20 reads of `current_user.role` across 9 files.** Every one becomes a refactor point in 1D.
- **Login uses FastAPI's `OAuth2PasswordRequestForm`** — form-encoded `username` + `password` per OAuth2 spec. Industry-standard. Keep it.
- **Existing JWT contains** `sub` (user UUID), `tenant_id`, `role`. 1B renames `role` to `active_role`.
- **Two existing endpoints:** `POST /auth/login` and `GET /auth/me`. 1B adds `POST /auth/roles-for-email`. 1A.7 adds `POST /users/{id}/roles` and `DELETE /users/{id}/roles/{role}` for Owner-only role assignment.

---

## Phase 1A — Add multi-role schema (backward-compatible) ✅ DONE 2026-05-07

**Goal:** Database can represent users with multiple roles; existing code paths unchanged.

- [ ] **1A.1** Migration `p1_add_user_roles_table` — new `user_roles` join table (`id`, `user_id`, `role`, `assigned_at`, `assigned_by_user_id`, unique constraint on `(user_id, role)`)
- [ ] **1A.2** Migration runs backfill: every existing user gets one row in `user_roles` matching their current `users.role` value
- [ ] **1A.3** ORM: add `UserRoleAssignment` model + `User.role_assignments` relationship (lazy=selectin)
- [ ] **1A.4** Repository helper: `get_user_authorized_roles(user_id) -> list[UserRole]`
- [ ] **1A.5** Tests: backfill correctness, multi-role assignment, unique-constraint enforcement
- [ ] **1A.6** Run full test suite — must stay green (existing call sites still read `users.role`, untouched)

**Phase 1A done when:** new table exists, backfilled, full test suite green, zero call-site changes outside `app/modules/auth/`.

> **Note on tests (2026-05-07):** per project precedent (see `tests/test_reports_flow.py` header), DB-write tests inside the test process hit a known asyncpg/pytest-asyncio interaction. 1A coverage is achieved through (a) the functional smoke tests we ran against real data after each step (1A.2, 1A.3, 1A.4) and (b) HTTP-layer tests written in Phase 1B that transitively exercise the 1A repository helpers and ORM. The async-test-infra rebuild stays in Appendix A as its own future phase.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

## Phase 1B — New login endpoints alongside old (parallel paths) ✅ DONE 2026-05-07

**Goal:** Backend can accept the new two-step login; old login still works for unmodified clients.

- [ ] **1B.1** New endpoint `POST /auth/roles-for-email` — given an email, returns the roles the user is authorized for. No password needed; this is the role-picker step. Rate-limited to prevent enumeration.
- [ ] **1B.2** Modify `POST /auth/login` to *optionally* accept `requested_role` form field. If present, verify it's in user's authorized set; reject 403 if not. If absent, fall back to user's `users.role` (existing behavior).
- [ ] **1B.3** JWT now encodes `active_role` (the role chosen at login). Old `role` claim still emitted for backward compatibility during 1C/1D rollout.
- [ ] **1B.4** New helper `get_active_role(current_user, request) -> UserRole`: reads `active_role` from JWT first; falls back to `current_user.role` if claim missing (handles tokens issued before 1B). All future code paths use this helper instead of `current_user.role`.
- [ ] **1B.5** New Pydantic schemas: `RolesForEmailRequest`, `RolesForEmailResponse`, `LoginRequestV2` (extends existing with optional `requested_role`).
- [ ] **1B.6** New endpoints (Owner-only): `POST /users/{user_id}/roles` (assign role), `DELETE /users/{user_id}/roles/{role}` (revoke role). Idempotent.
- [ ] **1B.7** Tests: roles-for-email returns correct set, login with valid role 200, login with unauthorized role 403, login without role works (backward compat), JWT carries `active_role`, helper falls back correctly on old tokens.

**Phase 1B done when:** all new endpoints working, old endpoints unchanged, full test suite green, both old and new login flows functional.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

## Phase 1C — Frontend: new login UI + TopBar dropdown + session-expiry modal ✅ DONE 2026-05-07

**Goal:** Users get the new two-step login experience. The 5 dev seed accounts still work for testing.

- [ ] **1C.1** Two-step login UI — Step 1: email input + Continue button → calls `/auth/roles-for-email` → renders role cards for which the user is authorized.
- [ ] **1C.2** Step 2: password input + Sign In button + Back button (returns to step 1, email preserved).
- [ ] **1C.3** Validation: empty email inline error; unknown email inline error after step 1; wrong password inline error on step 2.
- [ ] **1C.4** Loading state: disable inputs + spinner on submit. Error state: 401 inline, 5xx toast. Empty state: not applicable.
- [ ] **1C.5** Keyboard: Enter advances step 1; Enter submits step 2; Esc clears errors.
- [ ] **1C.6** State persistence: refresh on step 2 → stays on step 2 with email preserved.
- [ ] **1C.7** Move 5 hardcoded dev accounts out of `LoginForm.tsx` into a `<DevModeAccountPicker />` component, gated by env flag (visible in dev only).
- [ ] **1C.8** TopBar avatar refactor: replace single-click logout with dropdown — items "Profile" (→ /settings), "Switch Role" (only if user has >1 role; routes to login step 1 with email preserved), "Sign Out" (logout + → /login).
- [ ] **1C.9** Dropdown UX: Esc closes, Tab traverses, click-outside closes, focus returns to avatar after close.
- [ ] **1C.10** Session expiry modal: axios interceptor catches 401 globally → shows modal "Your session has expired. Please sign in again to continue." → user clicks OK → save current path to `localStorage.lastPath` → navigate to login step 2 (skip role picker; remember last role from `localStorage.lastRole`) → after successful re-login, restore `lastPath`.
- [ ] **1C.11** Manual browser test: log in as Omar (1 role) — Step 1 returns 1 role, advances cleanly. Log in as a multi-role test user — Step 1 returns the set, picker works. Trigger session expiry — modal works, credentials-only re-login works, deep-link preserved.

**Phase 1C done when:** all 8 UX criteria pass on login + TopBar; both old and new login work end-to-end; manual browser test verified across roles.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

## Phase 1D — Migrate the 20 call sites to the new contract (sweep)

**Goal:** Every `current_user.role` read in the codebase uses the new `get_active_role()` helper. Old `role` claim removed from JWT. Schema cleanup.

This is the most mechanical phase. Each file gets edited, tests run, commit, move to next. No file is changed without its test suite passing first.

The 9 files identified in recon (in dependency order):

- [ ] **1D.1** `app/modules/auth/router.py` line 100 (the `/me` endpoint) — uses helper, returns active role.
- [ ] **1D.2** `app/modules/auth/access_guards.py` lines 36, 50, 92 — guards check `get_active_role()` instead of `current_user.role`.
- [ ] **1D.3** `app/modules/auth/service.py` line 55 — JWT encoder writes `active_role`, drops legacy `role` claim.
- [ ] **1D.4** `app/modules/bars/router.py` line 152.
- [ ] **1D.5** `app/modules/alerts/router.py` lines 88, 130, 166, 204.
- [ ] **1D.6** `app/modules/warehouse/router.py` lines 81, 107, 129–131, 478–480.
- [ ] **1D.7** `app/modules/predictions/router.py` line 52.
- [ ] **1D.8** `app/modules/reports/router.py` line 61.
- [ ] **1D.9** `app/modules/chat/service.py` line 671.
- [ ] **1D.10** Migration `p2_drop_users_role_column` — once all call sites migrated, drop the redundant `users.role` column. The active role lives in JWT; assigned roles live in `user_roles`.
- [ ] **1D.11** Final manual browser test all 4 roles: Owner, Manager, Bartender, Warehouse — every page loads, every guard fires correctly.
- [ ] **1D.12** Commit + PR + squash-merge to `develop`.

**Phase 1D done when:** all 20 call sites migrated, `users.role` column dropped, all tests green, all 4 roles verified end-to-end in browser.

**Completion record:** `[done] YYYY-MM-DD — commit ________`

---

**Phase 1 done when:** all 4 sub-phases complete, all 8 UX criteria pass on login + TopBar, multi-role login verified end-to-end with at least 2 different role assignments, no regressions.

**Phase 1 completion record:** `[done] YYYY-MM-DD — commit ________`

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

<!-- phase-2-progress -->

## Phase 2 — Owner experience audit ✅ COMPLETE 2026-05-07

Recon performed via Claude in Chrome on 2026-05-07. 11 owner-visible pages
walked. Findings triaged into batches:

### Batch A — Data hygiene ✅ DONE 2026-05-07
- Deleted 4 test events (new event, Lifecycle Test, Backend Test Event TEST,
  Sundance June 66) — cascaded out 3 bars, 2 reports, 1 event_product, 1 bar_stock
- Deleted 2 in-event test bars (Chat Hook Test Bar, Smoke Test Bar 1776418247)
  — cascaded 2 channels, 5 alerts, 3 bar_stock, 12 stock_transactions
- Deleted 29 test chat messages across two sweeps
- Renamed live event "Browser Created Test" → "Sundance 2026"
  (date 2026-06-19, expected_guest_count 5000)
- Active event UUID e7866455-b721-419e-8d10-e5e157ff50d6 unchanged
- Final state: 1 event, 23 bars, 11 channels, 21 chat messages
- Backup: backups/xproject_dev_pre_cleanup_20260507_181107.sql
- Verified end-to-end via Claude-in-Chrome 5-check pass

### Batch D — One-liners ✅ DONE 2026-05-07
- Literal `\u00b7` rendered as text on Event detail header → fixed at
  EventDetailPage.tsx:292 (replaced literal with actual `·`)
- Reports stat math → auto-resolved by Batch A (zero completed events
  now correctly displays 0/€0/—; empty-state copy improvement moved
  to Batch C)

### Batch C — Dashboard polish ✅ DONE 2026-05-07
- 'Most bars quiet' banner: appears above bar grid when ≥80% of bars
  have zero revenue/drinks. Auto-hides once enough bars are active.
- FreshnessBadge tooltip: 2-word label → full explanatory sentence
  mentioning Slesh POS + sandbox credentials.
- Reports TOTAL EVENTS tile: 'After your first event ends' hint when
  zero completed events.

### Batch B — Inventory rewrite ✅ DONE 2026-05-07
- /inventory now uses dashboard hooks + new selector at
  features/inventory/selectors.ts; mock imports removed.
- 4-state guards added; unwired metrics render '—' consistently.

### Deferred (post-Sundance)
- URL state for tabs (Catalog Products/Recipes, Alerts filter, Chat channel)
- Loading skeletons on F5 (all 11 pages)
- Alerts "Warning" filter scope inconsistency
- Multiple "ships in v1.1" footnotes

<!-- phase-3-progress -->

## Phase 3 — Manager experience audit ✅ COMPLETE 2026-05-08

Recon performed via Claude in Chrome on 2026-05-08 with
manager.cocktail@nomagroup.it (assigned to Cocktail Bar — the only bar
with real Phase F seed data). Manager experience already mostly correct:
sidebar trimmed to 5 items, anomaly/owner-only alerts hidden correctly,
chat scoped, settings own-account-only, 5 of 6 owner routes already
guarded. Two real issues found, batched as E + F.

### Batch E — /reports route guard ✅ DONE 2026-05-08
- /reports route accepted canGenerateReport OR canGenerateBarReport,
  letting Managers land on broken Owner chrome (KPI tiles stuck loading
  because backend correctly returned 403).
- Tightened to canGenerateReport only. Managers now redirect to
  /dashboard, matching the 5 other Owner routes.
- canGenerateBarReport flag preserved in usePermissions for future use
  when a Manager-scoped bar report page is built.

### Batch F — Inventory page Manager scoping ✅ DONE 2026-05-08
- usePermissions().assignedBarId now drives a single-bar collapse on
  InventoryPage. When non-null:
    * bars[] and products[] selectors filter to that bar
    * bar filter pills hidden
    * 4-card summary grid hidden
    * header subtitle reads 'X products at <bar name>'
- Owner / Warehouse (null assignedBarId) see the full view, unchanged.
- Export CSV intentionally kept (role-neutral 'save current view'
  affordance, not Owner-privileged).

### Polish-week items (deferred)
- "ACTIVE ALERTS 0 all clear" KPI on My Bar contradicts visible
  acknowledged CRITICAL alert below — relabel to "0 unacknowledged"
- Self-DM channel "Manager Cocktail Bar ↔ …" (seed data hygiene)
- Bottom-left sidebar swap-icon dev affordance still visible

<!-- phase-4-progress -->

## Phase 4 — Bartender experience audit ✅ COMPLETE 2026-05-08

Recon performed via Claude in Chrome with bartender.marco@nomagroup.it
(Bartender at Cocktail Bar). Bartender experience was already cleaner
than expected because Batch F's `assignedBarId` work auto-scoped
Inventory for Bartender at zero additional cost.

All 7 Owner-only direct URL probes redirect to /dashboard correctly.
Real issues found: 4, batched as G.

### Batch G — Bartender polish (DONE 2026-05-08)
1. Sidebar: 'Scan Bottle' stub removed from Bartender nav. Route
   guard preserved for Phase 6 restoration.
2. Sidebar identity card: shows user.full_name (was role label);
   icon button replaced with proper Sign Out icon + tooltip.
3. InventoryPage: BAR + UNIT PRICE columns hidden in single-bar
   view (benefits Manager too — Batch F + G compose).
4. InventoryPage: Export CSV hidden in single-bar view.

### Polish-week / deferred (not Sundance-blocking)
- 'Active Alerts' KPI logic already correct; recon confusion was
  about the panel below, not the counter.
- Real /scan UI is Phase 6 territory.
- Alert text race between two adapter shapes (Mojito alert flickering
  between two copies) — flagged for Phase 7 cross-role bug-hunt.
