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

  (none yet — fill in as you go)

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
