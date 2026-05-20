# Pre-Sundance Must-Ship Plan

Produced by state-of-project audit completed 2026-05-18.
Source: docs/audits/state-of-project-2026-05-17.md

Sundance go-live: 2026-06-19 (32 days from audit completion)
Effective working window: 27-28 days (after 4-5 day hard freeze)
Estimated must-ship work: 16-19 days
Buffer after risk reserves: 0-4 days (TIGHT but achievable)

---

## Priority order

### WS1.  RF33 — Phase 1D auth migration (CRITICAL)

Estimate: 1-2 days
Target: 2026-05-19 to 2026-05-20

Scope:
  1. Add get_active_role(current_user, request) helper
  2. Migrate 20 call sites from current_user.role to helper
  3. Alembic migration p2_drop_users_role_column
  4. Browser-test all 4 roles
  5. Commit each call-site migration separately

Success criteria:
  - grep current_user.role returns 0 hits in app/
  - users.role column gone from DB
  - All 4 roles login + authorize end-to-end

### WS2.  RF37 — Real Phase 7 cross-role bug hunt (HIGH)

Estimate: 4-5 days
Target: 2026-05-21 to 2026-05-25

Scope:
  1-4. Full walkthrough per role (Owner, Manager, Bartender, Warehouse)
  5. Cross-role flows
  6. Role-switching test
  7. Session expiry test
  8-10. Fix all S1, S2, S3 bugs
  11. Document remaining S3/S4 in docs/known-issues.md

Includes B9 alert text race, B3 alerts filter, RF31 adapter inconsistency.

Success criteria:
  - Zero S1 bugs
  - Zero S2 bugs
  - docs/known-issues.md exists

### WS3.  RF21 — Phase 8 Sundance dress rehearsal (CRITICAL)

Estimate: 3-5 days
Target: 2026-05-27 to 2026-06-01

Scope:
  8.1  Simulation event setup
  8.2  Multi-role concurrent test (real devices)
  8.3  Failure modes (4: backend down, slow network, session expiry, concurrent chat)
  8.4  Performance (dashboard under 3s, WS reconnect under 5s, no memory leak)
  8.5  Fix + re-test

Includes C7 physical device test.

### WS4.  Phase 9 — ML + recipes (OMAR-GATED)

Estimate: ~5 days
Target: parallel to WS2-3 once Omar provides recipe data

Decision gates:
  Q2: Recipe data DEADLINE 2026-05-25
  Q3: Slesh sandbox credentials (workaround: historical CSVs)

Prereqs: A8 ORM mapper, D1 recipe seeding, D5 GENERIC_MENU_NAMES, E1 weather

---

## Polish sprint (~1 day, target 2026-06-08)

  B5   ACTIVE ALERTS KPI mislabel
  B7   Dev affordance still in sidebar
  B10  Settings copy "Reports are already bilingual" bug
  B13  Inconsistent role labels
  D4   S8 admin slesh-poll-state endpoint

## Sundance-critical (folded into WS2)

  B3   Alerts Warning filter scope
  B9   Alert text race
  RF41 Change-password feature (0.5 day; Omar will notice)

## Other PRE-SUNDANCE items

  A6   Polling worker smoke test (before WS3)
  C4   Post-event report generator
  B11  Allocations UI (only if dress rehearsal shows friction)

---

## Scope reduction levers (if timeline tightens)

  A. Defer Detector #6 (C1) to post-Sundance — saves 1-2 days
  B. Defer Allocations UI (B11) — saves 0.5 day
  C. Trim Phase 9 to single-model MVP — saves 2 days
  D. Reduce Phase 7 to 2-role walkthrough — saves 1-2 days

Maximum reduction: 4-5 days.  Brings buffer from 0-4 to 4-9 days.

---

## Schedule

2026-05-19  Mon  WS1 start (Phase 1D auth)
2026-05-20  Tue  WS1 finish
2026-05-21  Wed  WS2 start (real Phase 7)
2026-05-22  Thu  WS2 day 2
2026-05-23  Fri  WS2 day 3 + RF41 change-password
2026-05-24  Sat  WS2 day 4 (cross-role flows)
2026-05-25  Sun  WS2 finish (Omar recipe DEADLINE)
2026-05-26  Mon  Polish sprint + Phase 9.1 start
2026-05-27  Tue  WS3 start (dress rehearsal setup)
2026-05-28  Wed  WS3 day 2 (multi-role test)
2026-05-29  Thu  WS3 day 3 (failure modes)
2026-05-30  Fri  WS3 day 4 (performance)
2026-05-31  Sat  WS3 day 5 (fix + retest)
2026-06-01  Sun  Phase 9
2026-06-02  Mon  Phase 9
2026-06-03  Tue  Phase 9
2026-06-04  Wed  Phase 9 finish
2026-06-05  Thu  Buffer
2026-06-06  Fri  Buffer
2026-06-07  Sat  Buffer
2026-06-08  Sun  Polish sprint remaining
2026-06-09  Mon  Final smoke test
2026-06-10  Tue  Final smoke test
2026-06-11  Wed  Hard freeze
2026-06-12  Thu  Freeze
2026-06-13  Fri  Freeze
2026-06-14  Sat  Freeze
2026-06-15  Sun  Freeze + Omar walkthrough
2026-06-16  Mon  Freeze + on-site prep
2026-06-17  Tue  On-site
2026-06-18  Wed  On-site
2026-06-19  Thu  SUNDANCE GO-LIVE

---

Last updated: 2026-05-18
Next update: after WS1 ships


---

## Schedule revisions

  WS1 ACTUAL: 2026-05-19 (1 calendar day from audit completion)
  WS1 completed in ~3 hours of focused work.
  10 commits landed on origin/develop.
  
  Schedule shifts forward by 1 day vs the original May 18 plan:
    WS2 (real Phase 7 cross-role bug hunt): start 2026-05-20
    WS3 (Phase 8 dress rehearsal): start 2026-05-28
    Phase 9 (ML + recipes, Omar-gated): in parallel with WS2-3
  
  Days remaining to Sundance (2026-06-19): 31
  Buffer remaining: still 0-4 days after risk reserves
  
  Phase 1D-full (remove in-memory shim + drop users.role column)
  moved to post-Sundance backlog.  Phase 1D-min (helper + 20 sites
  migrated) is RF33's resolution scope for pre-Sundance.
