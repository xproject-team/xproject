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

### F11a — RESOLVED 2026-05-21 — Duplicate "Arancine" catalog entries

  Role:        Owner (affects /catalog)
  Severity:    S3 (ambiguous catalog → operator confusion, no data loss risk)
  Page/Route:  /catalog
  Reported:    Owner walkthrough via Claude in Chrome
  Resolved:    2026-05-21 via DB delete

  Root cause (investigation findings):
    Two distinct products rows for "Arancine":
      - db6ae7cf (Slesh ID 68716f81...) created May 1 23:51:08.819
      - 0a515545 (Slesh ID 684801bc...) created May 1 23:51:08.825
    
    Same name, same product_type=food, same default_price_cents=500.
    Both had unique external_pos_id (different Slesh mappings).
    Both created within the same seed script run.
    
    Dependency check showed ZERO FK refs on either row:
      bar_stock: 0    stock_tx: 0    event_products: 0
      alerts:    0    as_drink: 0    as_ingredient: 0
    
    Hypothesis: a seed script generated two Slesh-POS items for the
    same logical product (likely an off-by-one in the import loop
    that mapped multiple Slesh negozio_id values to the same name).

  Resolution:
    Single-statement deletion in a transaction:
      DELETE FROM products WHERE id = '0a515545-e00b-422d-bb66-ea95d6b66481';
    
    Kept db6ae7cf as the canonical row (older external_pos_id, assumed
    canonical in Slesh sandbox).  No FK migration needed — both rows
    had zero dependencies.

  Verification:
    Pre-delete:  2 rows named "Arancine"
    Post-delete: 1 row named "Arancine"  ✓
    Total products: 71 → 70
    
  Backup: backups/xproject_dev_pre_arancine_dedup_20260521_131046.sql

---

### F11b — DEFERRED — "Cartoccio Misto" vs "Cartoccio misto" (case + price)

  Role:        Owner (affects /catalog)
  Severity:    S3 (naming ambiguity, not data integrity)
  Page/Route:  /catalog
  Reported:    Owner walkthrough via Claude in Chrome
  Status:      DEFERRED — needs Omar input

  Root cause investigation:
    Three Cartoccio rows in the catalog, NOT duplicates:
      - "Cartoccio Misto"   8€   Slesh ID 684801bc262443f1a08c8d23
      - "Cartoccio misto"   10€  Slesh ID 685d2b3544d5451586f56329
      - "Cartoccio Fritti"  8€   Slesh ID 687f4e6dcfd860a827401f0c
    
    All 3 have distinct external_pos_id values → Slesh treats them
    as separate menu items.  Different prices (8€ vs 10€) suggest
    intentional variants (e.g., portion sizes).
    
  Why NOT merge:
    Merging would mean one external_pos_id is lost.  Slesh POS tx
    arriving for the lost ID would either drop at the adapter or
    fail to match a product.  This is real Sundance revenue risk.
    
  Recommendation for Omar:
    Confirm whether the 8€ and 10€ Cartoccio Misto variants are:
      (a) Intentional sizes (e.g., piccolo/grande) → rename to disambiguate
      (b) An accidental duplicate → merge one Slesh ID into the other
    
    Pre-Sundance action depends on Omar's answer.
    
  Action today: documented as deferred; no DB change.

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
