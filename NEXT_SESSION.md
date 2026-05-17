# Next Session Handoff — Post-Phase-8, Pre-Phase-9

**Updated:** 2026-05-17 by Hesam + Claude
**Resume context:** Phase 8 closed cleanly; Phase 9 gated on Omar conversation
**Replaces:** the May 12 version (now obsolete; Phase 8 closed)

---

## What just shipped (May 13 - May 17)

Phase 8 — Slesh integration into the reconciliation report — closed
end-to-end. Eleven commits over five days. Variance signal now flows
from the Slesh POS data through SQL, schema, service, frontend types,
and the reconciliation page with HONEST status semantics.

Commits in order:

  331726d  S1 cron registration
  cd9e820  S2 smoke test PASS
  97d861d  S3 honest missing_pos_data flag
  054f1bc  S4 pos_sales SQL CTE
  36ca95d  Sundance 2025 CSVs staged
  8fed909  Sundance 2024 CSVs staged + KNOWN_ISSUES.md
  8bec41e  catalog categorization (14 product UPDATEs)
  f5b2594  S5 schema + service populate POS variance
  18e33d9  S6 frontend display of POS variance
  ed98938  S7 three-role security verification record
  7b6196b  S9 phase closure documentation

Total: ~700 lines new code + ~535 lines documentation.
Zero rollbacks. Zero regressions.
All on origin/develop.

---

## Where Phase 8 left things

  The variance signal works.  When the system has POS data for a
  bottle-level product, it computes consumed_via_pos_qty - scanner
  consumed and renders the result with a tier-coded status pill.

  When the system doesn't have POS data, or the product is a generic
  menu item (Cocktail, Sprtiz, etc.), the row honestly shows "—" and
  a NO_POS_DATA or NEEDS_RECIPE pill.  The system never fabricates.

  The cascade is ready.  The reconciliation_service.py has a hardcoded
  GENERIC_MENU_NAMES set that surfaces NEEDS_RECIPE for 8 known menu
  items.  When Phase 9 lands recipes, products move OUT of this set
  automatically and start showing real variance numbers.

  Defense-in-depth verified.  Owner sees full page, Manager and
  Bartender get blocked at the frontend gate + route guard + backend
  403.  PermissionDeniedToast fires correctly.  Documented in
  docs/phase8-s7-verification.md.

---

## What is explicitly NOT done

  Recipe seeding for the 8 generic menu items
  ML Model A demand forecasting
  Whitespace dedup for 13 products with trailing-space names
  2023 data extraction (pre-Slesh manual Excel era; deferred indefinitely)
  S8 admin slesh-poll-state endpoint (out of MVP scope)
  Brand-specific ingredient products (operational decision pending)
  Phase 6.14 physical-device dress rehearsal (still pending)
  Pre-Sundance smoke test (do ~3 days before June 19)

See docs/phase8-closure.md sections 4-6 for the full reasoning chain
on each deferral.

---

## Critical Omar conversation queue

These four questions block Phase 9.  Drop them into the next Omar
conversation as a structured agenda:

  Q1. Will the 2026 Slesh menu match the 2025 menu?  Specifically:
      are the 24 cocktails from the 2024 DRINK-LIST returning, or
      has the menu shifted to fewer signature drinks?

  Q2. For each cocktail in the 2026 menu: what is the pour quantity
      per ingredient (e.g., 60ml vodka, 30ml lime, 20ml syrup)?

  Q3. Is the bar-to-Slesh-experience mapping in bars.slesh_experience_id
      current and accurate for 2026?  Specifically: does Cocktail Bar
      still use the same Slesh experience ID it did in 2025?

  Q4. The Aug 4 2024 Slesh data extract appears to be a byte-for-byte
      duplicate of Jul 28 (see data/sundance-2024/KNOWN_ISSUES.md).
      Was that a real ops issue or a Slesh export bug?

---

## Where to start when you resume

Three honest paths.  Pick based on whether the Omar conversation has
happened yet:

### Path A — Omar conversation HAS happened (Phase 9 unblocked)

Phase 9 workstreams in priority order:

  9.1  Recipe seeding from Omar's pour-quantity input
       Input: Q1 + Q2 answers from above
       Tech: similar pattern to categorize_slesh_products.py — dry-run
             script with pg_dump backup + single-transaction commit
       Output: ~10-25 rows in recipes + ~50-100 in recipe_items
       Effect: GENERIC_MENU_NAMES set becomes obsolete; rows transition
               from NEEDS_RECIPE to OK / OVER_POUR_* / UNDER_SCAN_*

  9.2  ML Model A — demand forecasting
       Input: ~39,000 historical orders across data/sundance-2024 +
              data/sundance-2025
       Tech: pandas + scikit-learn or LightGBM, NOT Postgres
       Reference: docs/predictions-module-spec.md
       Output: pickled model + inference endpoint + frontend chart

  9.3  Whitespace dedup
       One evening's commit.  Check FK refs, archive the dups, trim
       the survivors.  Defer until after Sundance unless it blocks.

### Path B — Omar conversation has NOT happened yet

Two unblocked tracks while waiting:

  B.1  Phase 6.14 physical-device dress rehearsal
       See docs/scanner-dress-rehearsal-checklist.md
       Real phone, real bottles, ~30 min of mechanical tests
       Verifies the four things DevTools cannot: audio, haptic, real
       camera, real offline behavior
       Pre-Sundance gating item

  B.2  Pre-Sundance smoke test prep
       Build a checklist for the ~3 days-before-Sundance final
       verification.  Pattern: a single document with go/no-go
       criteria for every subsystem (auth, scanner, dashboard,
       chat, alerts, reconciliation, Slesh poller, warehouse).

### Path C — Recipe seeding even without Omar input (least preferred)

If Omar conversation is delayed and you need to make Phase 9 progress:

  Build recipe seeding script with PLACEHOLDER quantities (1 unit
  per ingredient).  Mark every recipe with a tag like
  is_provisional=true.  Re-run with real quantities when Omar
  provides them.

  Risk: the system shows variance numbers based on guessed
  quantities.  Reconciliation page might mislead Omar.  Avoid
  unless Sundance is < 1 week away.

---

## Background reading if context is lost

Read in this order:

  1. THIS file
  2. git log --oneline -15  (see what just shipped)
  3. docs/phase8-closure.md  (full Phase 8 retrospective + Phase 9 plan)
  4. docs/phase8-s7-verification.md  (security gate verification record)
  5. docs/scanner-architecture.md  (Phase 6 background, the parent)
  6. docs/slesh-integration-roadmap.md  (older Slesh B1-B8 work)
  7. data/sundance-2024/KNOWN_ISSUES.md  (the Aug 4 duplicate issue)

The userMemories at the top of the Claude session will give you most
of the live state.  This doc is the structured handoff.

---

## Useful current state queries

When you resume, these confirm the world is still the way this doc
describes:

  # Confirm we are on develop, at 7b6196b or later
  cd ~/Projects/xproject && git log --oneline -3

  # Confirm Sundance 2026 is still the active live event
  psql -d xproject_dev -c "SELECT id, name, status FROM events
    WHERE tenant_id = '25ef916c-a288-44ae-b17c-8dfd09390834'
      AND status = 'live';"

  # Confirm catalog still categorized
  psql -d xproject_dev -c "SELECT product_type, COUNT(*) FROM products
    WHERE tenant_id = '25ef916c-a288-44ae-b17c-8dfd09390834'
      AND is_archived = false
    GROUP BY product_type ORDER BY product_type;"
  # Expected: drink=14, food=49, ingredient=3, supply=5

  # Confirm Phase 8 docs landed
  ls -la docs/phase8-*.md
  # Expected: phase8-closure.md (~14 KB), phase8-s7-verification.md (~8 KB)
