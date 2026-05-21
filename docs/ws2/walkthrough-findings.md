# WS2 — Real Phase 7 Cross-role Walkthrough Findings

**Started:** 2026-05-20
**Branch:** develop @ de0909f
**Goal:** systematic role-by-role discovery of S1+S2 bugs before Phase 8 dress rehearsal

## Severity scale

  S1  System unusable for this role (cannot complete primary task)
  S2  Feature broken (workaround exists, but degraded experience)
  S3  Ugly / confusing (works but unpolished)
  S4  Cosmetic (visual nit)

## Format per finding

  ### F<N>  <one-line summary>

    Role:        Owner | Manager | Bartender | Warehouse Staff
    Severity:    S1 | S2 | S3 | S4
    Page/Route:  /events/...
    Steps:       1. ...  2. ...  3. ...
    Expected:    ...
    Actual:      ...
    Notes:       (optional)

---

## Owner walkthrough  (2026-05-20)

  Goal: navigate every page; perform every action; log every weird thing.

  Test data: Sundance 2026 (UUID e7866455-b721-419e-8d10-e5e157ff50d6)
  Credentials: omar@nomagroup.it / xproject2026 / role=owner
  Frontend URL: http://localhost:5174

### Findings

### F10 — RESOLVED 2026-05-20 — Duplicate "Cocktail Bar" entries

  Role:        Owner (affected all 4 roles)
  Severity:    S2 (data integrity → user confusion across all surfaces)
  Page/Route:  /bars, /dashboard, /chat, /alerts
  Reported:    Owner walkthrough via Claude in Chrome
  Resolved:    2026-05-20 16:15 CEST via DB merge

  Root cause (investigation findings):
    Two separate bar rows existed in the DB for the same physical Cocktail Bar:
      - 413072cf (created Apr 28): operational bar with 3 users, 4 bar_stock,
        20 manual_bartender tx, 6 scans, 1 depletion alert, 1 chat channel
        with 1 message.  No slesh_negozio_id.
      - 797ddc36 (created May 4): POS mirror with 502 slesh_pos tx, 6 anomaly
        alerts, 1 auto-backfilled channel with 0 messages.  Has slesh_negozio_id.
    
    Hypothesis: when Slesh sandbox came online May 4, operator/script created
    a new bar to receive POS data instead of UPDATEing the existing bar.
    Anomaly detector + auto-channel-backfill (WS1 commit afa53c9) propagated
    the duplicate appearance into the UI.

  Resolution:
    Transactional 8-statement migration:
      1. Move 6 alerts        from 797ddc36 to 413072cf
      2. Move 502 stock_tx    from 797ddc36 to 413072cf
      3. Update keeper        SET slesh_negozio_id = '684820e2f8e1514a1f5b2272'
      4. DELETE 797ddc36      (CASCADE-deletes its empty channel)
    Other UPDATE statements were 0-row no-ops (bar_stock, event_products,
    warehouse_scans, users had no rows on 797ddc36 — verified pre-flight).

  Verification:
    Pre/post DB counts match expected exactly:
      alerts 1 → 7, stock_tx 20 → 522, channels 1 (CASCADE OK), users 3 (preserved)
    Frontend verified across 4 pages: /bars (22 total), /chat (1 bar channel),
    /dashboard (1 tile), /alerts (7 alerts, all unified).
    Manager login still works (manager.cocktail user assignment preserved).

  Backup: backups/xproject_dev_pre_cocktail_merge_20260520_160712.sql (343K)

  Lessons for downstream fixes:
    - Bars with FK to users + alerts + stock_tx require dependency check
      BEFORE deletion.  CASCADE chains can silently wipe real data.
    - Slesh integration mapping should NEVER create a new bar — it should
      ATTACH to an existing bar via UPDATE slesh_negozio_id.  Worth
      reviewing the Slesh integration path post-Sundance to prevent recurrence.

---



---

## Manager walkthrough  (pending)

  Credentials: manager.cocktail@nomagroup.it / manager123 / role=manager

## Bartender walkthrough  (pending)

  Credentials: bartender.luca@nomagroup.it / bartender123 / role=bartender

## Warehouse Staff walkthrough  (pending)

  Credentials: warehouse.keeper@nomagroup.it / warehouse123 / role=warehouse_keeper

---

## Cross-role flow tests  (pending)

  Flow 1: Owner creates event > Bartender scans > Warehouse adjusts > Manager monitors
  Flow 2: Role-switching test (single user with multiple roles, if any exist in DB)
  Flow 3: Session expiry test (modal works, others unaffected)

---

## Triage decisions  (post-walkthrough)

  S1 (must fix pre-Sundance):
  S2 (must fix pre-Sundance):
  S3 (known issue, documented):
  S4 (post-Sundance backlog):
