# Next Session — Pick up here

**Last session:** 2026-05-21 — WS2 Tier 1 cleanup complete (8 substantive commits).
**Audit doc:** docs/audits/state-of-project-2026-05-17.md (1573+ lines)
**Action plan:** docs/pre-sundance-must-ship.md
**Backlog:** docs/post-sundance-backlog.md
**WS2 findings doc:** docs/ws2/walkthrough-findings.md

## What shipped (8 substantive WS2 commits on origin/develop)

    66a7ded  F9      catalog category labels (humanized via CATEGORY_LABELS)
    8909be1  F8      wristband date locale (it-IT → en-US)
    021bd64  F7+F7b  alert timestamps humanized (3 renders + helper)
    c8feaa1  F6      IT flag emoji repaired (broken codepoint pair)
    15ecf0c  F4      Total Events → Completed Events
    474f232  F1      Active Alerts → Unacknowledged (3 strings)
    08776d8  F11a    Arancine duplicate DELETED (DB row)
    31d4b54  F10     Cocktail Bar DUPLICATES MERGED (DB transaction)

    Plus deferred:
        F11b  Cartoccio Misto naming — Omar input needed (8€ vs 10€ variants)

    Lines changed: ~30 across ~10 files
    Verifications: ~10 separate browser tests, ZERO regressions
    Sundance days remaining: 30 (as of 2026-05-21)

## What's next — Tier 2 work

Order of priority:

    F2   Warning filter scope inconsistency           ~1 hr
         /alerts page Warning filter doesn't scope the Anomaly
         Detection section.  Need to trace filter state through both
         list + anomaly renders, scope correctly, verify with browser.

    F3   Duplicate alert rendering across panels      ~1 hr
         6 anomaly alerts appear in both the main /alerts list AND
         the Anomaly Detection section, showing as 12 items for 6
         alerts.  Decide canonical section, remove the other render
         OR filter the main list to exclude anomaly_type alerts.

    F15  Event detail bars count mismatch (S2)        ~30 min
         /events/{id} shows "4 bars" instead of 22.  Likely a stale
         count in event detail card vs actual bars list.

    F5   Change-password feature (RF41)               ~2-4 hr
         Settings page has shell only — needs:
             Backend endpoint POST /users/me/change-password
             Frontend form with old/new/confirm fields
             bcrypt hash + update
             Validation (length, complexity, mismatch)
             Browser smoke test

Plus deferred housekeeping (post-Sundance backlog):

    Currency formatter consolidation (WristbandActivityFeed.tsx:17 stays it-IT)
    File-local fmtRelative consolidation (BarDashboardView, WarehousePage)
    SettingsPage flag consistency vs ReportPage
    Embedded prompt-injection string source investigation (low priority)
    Phase 1D-full auth shim removal (backlog A0)

## Critical state — DO NOT FORGET

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

    backups/xproject_dev_pre_cocktail_merge_20260520_160712.sql  (343K, pre-F10)
    backups/xproject_dev_pre_arancine_dedup_20260521_131046.sql  (pre-F11a)

## Resumption command — morning start

    cd ~/Projects/xproject
    git log --oneline -10
    cat docs/ws2/walkthrough-findings.md | head -80

Then start F2.  Same discipline:
    recon → understand → confirm → atomic patch → verify → commit
