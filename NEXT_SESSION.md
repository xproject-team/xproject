# Next Session — Pick up here

**Last session:** 2026-05-19 — WS1 RF33 Phase 1D-min complete.
**Audit doc:** docs/audits/state-of-project-2026-05-17.md (1573+ lines)
**Action plan:** docs/pre-sundance-must-ship.md
**Backlog:** docs/post-sundance-backlog.md

## What shipped today

  10 commits on origin/develop, latest 334c811
  
  All 20 RF33 call sites migrated to get_active_role helper.
  Phase 1D-full (shim removal + drop column) deferred to post-Sundance
  as backlog item A0.

## Tomorrow's work — WS2 Real Phase 7 cross-role bug hunt

**Target start:** 2026-05-20
**Estimate:** 4-5 days
**Why:** systematic walkthrough by role surfaces S1/S2 bugs that
        would otherwise show up during Phase 8 dress rehearsal —
        exactly the wrong time.

## Scope (per master roadmap Phase 7 spec)

  1. Owner full walkthrough (60 min, log every issue)
  2. Manager full walkthrough (60 min)
  3. Bartender full walkthrough (60 min)
  4. Warehouse Staff full walkthrough (60 min)
  5. Cross-role flows (Owner creates event > Bartender scans >
     Warehouse adjusts > Manager monitors)
  6. Role-switching test (single user with multiple roles)
  7. Session expiry test (modal works, others unaffected)
  8. Triage bugs S1/S2/S3/S4 by severity
  9. Fix all S1 bugs (system unusable)
  10. Fix all S2 bugs (feature broken)
  11. Document S3/S4 in docs/known-issues.md

## Known bugs to look for (from audit)

  - B9   Alert text race (Mojito alert flickering between adapters)
  - B3   Alerts Warning filter scope inconsistency
  - RF31 Alert text race adapter shape inconsistency
  - RF41 Change-password feature missing (Settings page)
  - B5   ACTIVE ALERTS KPI mislabel
  - B7   Dev affordance still in sidebar

## Standard discipline reminders

  - Close editor windows before commits (RF44 lesson)
  - grep verify after each commit (no unintended changes)
  - Smoke test with Manager (expect 403) + Owner (expect 200)
  - One concern per commit
  - Atomic write with pre/post assertions

## Audit findings reference

  CRITICAL: RF21 (Phase 8 dress rehearsal — WS3, May 28)
  HIGH:     RF37 (real Phase 7 — STARTS TOMORROW)
  RESOLVED: RF33 (Phase 1D-min — WS1 done today)

  Days to Sundance (2026-06-19): 31
  Buffer after risk reserves: 0-4 days
