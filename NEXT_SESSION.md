# Next Session — Pick up here

**Last session:** 2026-05-23 — WS2 Tier 2 complete (5 substantive commits today, 13 in total over two days).
**Audit doc:** docs/audits/state-of-project-2026-05-17.md
**Action plan:** docs/pre-sundance-must-ship.md
**Backlog:** docs/post-sundance-backlog.md
**WS2 findings doc:** docs/ws2/walkthrough-findings.md

## WS2 status — Tier 1 + Tier 2 COMPLETE

13 substantive commits on origin/develop, zero regressions across all
verifications.  Sundance days remaining: 29.

### Tier 1 (yesterday — fast surface fixes)
    31d4b54  F10   Cocktail Bar merge (DB transaction)
    08776d8  F11a  Arancine dedup
    474f232  F1    Active Alerts → Unacknowledged
    15ecf0c  F4    Total Events → Completed Events
    c8feaa1  F6    IT flag emoji
    021bd64  F7+b  alert timestamps humanized
    8909be1  F8    wristband date locale
    66a7ded  F9    catalog category labels

### Tier 2 (today — state-management + features)
    c7b0f02  docs  NEXT_SESSION refresh
    f8344e1  F2    severity filter / anomaly section refactor
    65f22a2  F9-fu CATEGORY_LABELS TS narrowing
    e4c33ac  F3    anomalies disjoint from main list
    c39d745  F15   EventDetailPage real bars data
    9f317cc  F5    change-password feature (closes RF41)

### Deferred (Omar-gated)
    F11b  Cartoccio Misto naming — 8€ vs 10€ variants

## What's next — Phase 8 dress rehearsal

WS2 was scoped at ~15 findings; 12 of those resolved.  The remaining
items are housekeeping (post-Sundance backlog), not Sundance blockers.

Next milestone: **Phase 8 dress rehearsal** (originally scheduled
2026-05-28).  Goal: simulate the full Sundance flow end-to-end with
seed data, find anything the WS2 walkthrough missed.

Recommended day-1 of Phase 8:

    1. Run full-day smoke against the app (Owner + Manager +
       Bartender + Warehouse) — record every blip.
    2. Stress-test the alert pipeline by injecting synthetic
       stock-depletion events and verifying:
         - DepletionEvaluator fires correctly
         - DemandSpikeDetector fires correctly
         - RecipeDeviationDetector fires correctly
         - Alerts surface in /alerts AND /dashboard panel
         - Acknowledge flow works for each detector
         - WebSocket push delivers without polling fallback
    3. Run the report-generation flow end-to-end on a completed
       test event.
    4. Document any new findings in docs/ws2/dress-rehearsal.md.

## Post-Sundance backlog items collected during WS2

    A0  Phase 1D-full: drop users.role column, remove in-memory shim
    A1  Currency formatter consolidation
        (WristbandActivityFeed.tsx:17 still it-IT; dashboard header
        uses en-US — inconsistent)
    A2  File-local fmtRelative consolidation
        (BarDashboardView, WarehousePage both have private
        implementations; could share lib/utils.ts formatRelativeTime)
    A3  SettingsPage flag consistency vs ReportPage (one has
        flags, the other doesn't)
    A4  Embedded prompt-injection string source — appeared in
        Wristband Activity feed DOM text, source unknown,
        ignored at extension level per security policy
    A5  Pytest async-fixture loop-scope rework so multiple
        change-password tests run in one session (currently
        pass individually, fail on suite chaining due to a
        known pytest-asyncio limitation)
    A6  Force-relogin on password change (current behaviour:
        existing JWT remains valid until expiry)
    A7  Server-side rate-limit on change-password attempts
        (currently leans on the same overall login-bucket limits)
    A8  EventDetailPage bars table dashboard-quality fields
        (status indicator, staff count, stock %); requires the
        BarKpi composition from features/dashboard.  Today's
        table is functionally correct against the API surface.

## Critical state

    Backend:    localhost:8000 (uvicorn, native venv at ~/Projects/xproject/venv)
    Frontend:   localhost:5174 (Vite; 5173 typically busy)
    PostgreSQL: native, user mohammadhesam, DB xproject_dev
    Redis:      Docker on 6379
    MinIO:      Docker on 9000/9001

    Active event: Sundance 2026
                  UUID e7866455-b721-419e-8d10-e5e157ff50d6
                  status LIVE
    Tenant:       25ef916c-a288-44ae-b17c-8dfd09390834
    DB state:     22 bars, 70 products, 7 alerts (post-F10/F11)

## Test accounts

    Owner:     omar@nomagroup.it       / xproject2026
    Manager:   manager.cocktail@nomagroup.it / manager123
    Bartender: bartender.luca@nomagroup.it   / bartender123
    Warehouse: warehouse.keeper@nomagroup.it / warehouse123

## Backups (rollback points)

    backups/xproject_dev_pre_cocktail_merge_20260520_160712.sql  (pre-F10)
    backups/xproject_dev_pre_arancine_dedup_20260521_131046.sql  (pre-F11a)

## Resumption command — Phase 8 morning start

    cd ~/Projects/xproject
    git log --oneline -10
    cat docs/pre-sundance-must-ship.md | head -80

Then start Phase 8 dress rehearsal (or take a half-day; you've
earned it).  Same discipline holds:
    recon → understand → confirm → atomic patch → verify → commit
