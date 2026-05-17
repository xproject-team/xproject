# Phase 8 — Slesh Integration Closure

**Status:** Phase complete 2026-05-17 (S8 explicitly deferred, all other sub-steps shipped)
**Owner:** Hesam (technical lead)
**Spec for:** Phase 8 of the Sundance Readiness Roadmap
**Parent docs:** docs/slesh-integration-roadmap.md, docs/sundance-readiness-roadmap.md
**Successor:** Phase 9 (recipe seeding + ML Model A demand forecasting)

---

## 1. Phase 8 scope and outcome

Phase 8 wired the Slesh POS integration into the post-event reconciliation
report and surfaced the resulting variance signal in the UI with HONEST
status semantics. The phase delivers Omar a per-bar, per-product view of
where scanner-observed consumption diverges from POS-recorded sales — the
over-pour and under-scan signal that justifies the entire scanner
infrastructure.

The outcome is a system that reports what it knows and explicitly
declares what it does not. When a bottle product has POS data, the
variance is computed and flagged at the appropriate severity tier.
When a menu item is generic (Slesh sells "Cocktail" but inventory
tracks "Bacardi Rum 1L"), the row is honestly labeled NEEDS_RECIPE
rather than fabricated with a guessed variance number.

This honesty principle is the foundation of trust at Sundance. The
first time Omar drills into a row that displays a confidently-wrong
zero, the system loses credibility permanently. Honest "—" instead
of fake "0" is non-negotiable.

---

## 2. What shipped (chronological)

  S1 — Slesh cron registration                        commit 331726d
       Added the Slesh poller arq cron entry. Every 5 min, the poller
       pulls new orders and writes slesh_pos stock_transactions.

  S2 — Slesh cron smoke test                           commit cd9e820
       End-to-end verification that the cron fires, pulls real Slesh
       data, and persists. Single confirmed live event.

  S3 — Honest missing_pos_data flag                    commit 97d61d9
       Replaced the hardcoded missing_pos_data=True placeholder with
       runtime detection: the flag is true only when zero slesh_pos
       transactions exist for the event window. Honest signal from
       day one.

  S4 — pos_sales SQL CTE                               commit 054f1bc
       Extended the reconciliation SQL with a pos_sales CTE that
       aggregates Slesh sales per (bar, product, event). New columns
       emitted: consumed_via_pos_qty, pos_variance_qty.

       Catalog data staging                             commits 36ca95d
                                                                8fed909
       Extracted Sundance 2024 and 2025 historical data via Cowork
       to data/sundance-2024/ and data/sundance-2025/. Sundance 2023
       deferred (pre-Slesh manual Excel format). 2024 includes 24
       cocktail recipe ingredient lists in DRINK-LIST.

       Catalog categorization                           commit 8bec41e
       categorize_slesh_products.py with dry-run + pg_dump backup +
       single-transaction commit discipline. 14 product UPDATEs
       applied; 13 whitespace-name products explicitly deferred
       because some would collide with clean-name twins under the
       uq_products_tenant_name_type_active index.

  S5 — Schema + service populate POS                   commit f5b2594
       Extended ReconciliationRow with three new fields
       (consumed_via_pos_qty, pos_variance_qty, pos_variance_status)
       and ReconciliationTotals with four new counters
       (pos_pending_recipes_count, pos_ok_count, pos_over_pour_count,
       pos_under_scan_count). Added the _derive_pos_variance_status
       helper with 8 honest status branches mirroring the existing
       _derive_gap_flag pattern.

  S6 — Frontend display                                commit 18e33d9
       Extended the TypeScript types 1:1 mirror of the backend
       schema, added 4 POS StatCards to the summary section, added
       3 POS columns to the table (POS sold, Variance, Status),
       added the PosStatusPill component mapping 8 status values to
       color-coded badges. Extended local StatCard with 'success'
       and 'warning' emphasis values.

  S7 — Three-role browser verification                 commit ed98938
       Defense-in-depth verified via Claude in Chrome. All three
       layers fire correctly: frontend UI gate hides the entry-point
       for non-Owners, route guard redirects with
       PermissionDeniedToast, backend returns HTTP 403. See
       docs/phase8-s7-verification.md for the full record.

  S8 — Admin slesh-poll-state endpoint                 DEFERRED
       Out of MVP scope. Originally planned as an admin tool to
       show last-poll-timestamp, error count, retry status. Not
       needed for Sundance; can be added post-event if operational
       visibility into the poller becomes important.

  S9 — Phase closure documentation                     this commit
       This document.

---

## 3. Key architectural decisions

### 3.1 Defer recipes for Sundance MVP

The single highest-impact decision of Phase 8. The reconciliation
report depends on recipe-aware decomposition to compute bottle-level
variance from menu-level POS sales. We do not have pour-quantity data
from Omar; building recipes on guesses produces confident-looking
nonsense numbers. The system explicitly surfaces NEEDS_RECIPE for
generic menu items (Cocktail, Sprtiz, Birra, Analcolico, Shot, etc.)
instead of fabricating variance.

Reasoning chain: variance that is wrong at the bottle level is worse
than no variance signal at all. Wrong variance erodes trust the first
time Omar drills in and discovers the underlying assumption was a
guess. NEEDS_RECIPE is honest and self-explanatory; the user sees
exactly what the system knows and what it does not.

Phase 9 will land recipes derived from a combination of the 2024
DRINK-LIST data, Omar's pour-quantity input, and empirical fitting
against Sundance 2026's actual scanner-vs-POS data.

### 3.2 Use historical Slesh data as catalog source-of-truth

Rather than fabricating products or asking Omar for a complete menu
inventory, we extracted Sundance 2024 (9 CSVs, 23k orders) and 2025
(5 CSVs, 18k orders) via Cowork and staged them in data/. The
catalog categorization script reads the live products table (already
synced from Slesh) and applies name-keyed classifications grounded
in patterns observable in the historical data.

This is the standard data-engineering move: derive product categories
from real production data, not from interviews or guesses.

### 3.3 Two-layer null handling

The reconciliation SQL emits consumed_via_pos_qty as 0 (via COALESCE)
when no POS rows joined for a given (bar, product). The Python row
consumer then converts 0 to None before populating the Pydantic
schema. The "0" preserves SQL ergonomics (no SQL-level distinction
between absent and present-zero); the None preserves API honesty
(JSON null is rendered as "—" in the frontend rather than blending
in as zero).

This pattern should be replicated for any other report that has a
"true zero vs. missing data" distinction. Naming it explicitly here
documents the convention for Reza and future engineers.

### 3.4 GENERIC_MENU_NAMES as Phase 9 dependency hook

The _derive_pos_variance_status helper in reconciliation_service.py
contains a hardcoded set of 8 menu item names (Cocktail,
Cocktail signature, Cocktail Super premium, Sprtiz, Analcolico,
Shot, Gin Tonic, Birra) that are explicitly surfaced as NEEDS_RECIPE.

When Phase 9 lands recipes, the natural evolution is to replace this
hardcoded set with a runtime "does this product have a recipe?"
lookup. Products move OUT of the NEEDS_RECIPE state automatically as
recipes are added; no code change required per product.

The hardcoded set is intentional technical debt. It works for the
current scope (8 specific menu items), is trivially auditable, and
has a clear evolution path. Replacing it with a smart lookup before
recipes exist would be over-engineering.

### 3.5 Browser verification methodology

The Claude in Chrome verification pattern proved itself this phase
both positively and negatively. Positive: S7 confirmed defense-in-
depth across three roles in roughly 8 minutes of real time.
Negative: a methodology timing bug initially reported "silent
redirect, no toast" that turned out to be a verification artifact
(the toast auto-dismissed before the agent's second read_page fired).

Lesson preserved: use browser_batch (navigate + read_page in a
single round-trip) for any time-bounded UI element (toasts,
animations, transient errors). A standalone read_page after a
navigate cannot catch anything that resolves in less than the
network round-trip time.

This methodology note belongs in the test playbook for the future
end-to-end verification suite.

---

## 4. What we explicitly did NOT build

The following were considered, explicitly examined, and consciously
deferred:

  Recipe seeding for the 8 generic menu items
    Reason: no authoritative pour-quantity data from Omar. Phase 9
    work that requires either direct input from Omar or empirical
    fitting from Sundance 2026 data.

  Specific cocktail products (No.3 MULE, No.3 PINK, No.3 TONIC, etc.)
    Reason: 2024 DRINK-LIST has 24 cocktail compositions but Omar's
    2026 Slesh menu may not include them. Verify menu structure with
    Omar before fabricating products that may not exist.

  Whitespace dedup for 13 products with trailing spaces in name
    Reason: 'Arancine ' would collide with clean 'Arancine' under
    the uq_products_tenant_name_type_active unique index. FK
    references to stock_transactions, bar_stock, recipes,
    recipe_items, and warehouse_scans must be inspected before
    archiving the duplicate. Separate small commit; not a Phase 8
    concern.

  Admin slesh-poll-state endpoint (S8)
    Reason: out of MVP scope. The poller logs adequately for current
    needs. Operational visibility tool can ship post-Sundance if
    needed.

  ML Model A — demand forecasting
    Reason: Phase 9 scope. Training data is ready (~39,000 orders
    across Sundance 2024+2025). The pipeline design exists in
    docs/predictions-module-spec.md.

  Brand-specific ingredient products (Finlandia Vodka vs Vodka)
    Reason: inventory granularity decision deferred. The current
    schema supports both; the question is operational, not technical.
    Defer until Omar specifies how he tracks bottle inventory in
    2026.

---

## 5. Open questions for Omar

These need answers before Phase 9 recipe work can be honest rather
than guessed. Each should be raised in the next Omar conversation:

  Q1. Will the 2026 Slesh menu match the 2025 menu, or will there
      be additions or removals? Specifically: are the 24 cocktails
      from the 2024 DRINK-LIST returning, or has the menu shifted
      to fewer signature drinks?

  Q2. For each cocktail in the 2026 menu: what is the pour quantity
      per ingredient? (e.g., 60ml vodka, 30ml lime juice, 20ml
      sugar syrup per Mojito). Without this, recipe-based variance
      cannot be computed honestly.

  Q3. Is the bar-to-Slesh-experience mapping in
      bars.slesh_experience_id current and accurate for the 2026
      configuration? Specifically: does Cocktail Bar use the same
      Slesh experience ID it did in 2025?

  Q4. The Aug 4 2024 Slesh data extract appears to be a byte-for-
      byte duplicate of Jul 28 2024 (documented in
      data/sundance-2024/KNOWN_ISSUES.md). Was this a real
      operational issue (two events with same data) or a Slesh
      export bug we can ignore?

---

## 6. Phase 9 roadmap stub

Phase 9 is the value-creation phase that makes Phase 8's
infrastructure pay off. Three workstreams, in priority order:

### 9.1 Recipe seeding from authoritative data

Input: Omar's answers to Q1 and Q2 above + the 2024 DRINK-LIST as
reference.

Output: ~10-25 recipes in the recipes + recipe_items tables. Each
recipe maps a Slesh menu product to its bottle-level ingredient
composition with explicit ml or g quantities.

Effect on the system: GENERIC_MENU_NAMES set in
reconciliation_service.py becomes obsolete; rows transition from
NEEDS_RECIPE to OK_WITHIN_THRESHOLD / OVER_POUR_* / UNDER_SCAN_*
based on real variance computation.

Verification: re-run the S7 three-role verification suite. The
status pills will now show varied tiers instead of all NO_POS_DATA /
NEEDS_RECIPE.

### 9.2 ML Model A — demand forecasting

Input: ~39,000 historical orders across Sundance 2024 + 2025.
Source: data/sundance-2024/ and data/sundance-2025/ CSVs already
staged.

Output: a model that predicts per-bar, per-hour drink demand given
weather, expected guest count, and product category. Used for
inventory provisioning before each event.

Tech: pandas pipeline, scikit-learn or LightGBM, not Postgres.
Original design captured in docs/predictions-module-spec.md.

### 9.3 Whitespace dedup as a separate small commit

Input: the 13 products with trailing spaces in their names
identified by categorize_slesh_products.py.

Output: one of two paths per product, depending on FK reference
counts:
  - If the clean-name twin has all FK references, archive the
    trailing-space duplicate (set is_archived = true)
  - If the trailing-space row has references that would need
    migration, do the migration first, then archive

This is a one-evening commit. Standard dry-run + pg_dump backup +
single-transaction commit discipline. Defer until after Sundance
unless it becomes a blocker.

---

## 7. References

All Phase 8 commits on origin/develop:

  331726d  S1 — Slesh cron registration
  cd9e820  S2 — smoke test PASS
  97d61d9  S3 — honest missing_pos_data flag
  054f1bc  S4 — pos_sales SQL CTE + variance columns
  36ca95d  data — Sundance 2025 CSVs staged
  8fed909  data — Sundance 2024 CSVs staged + KNOWN_ISSUES.md
  8bec41e  feat(catalog) — categorize_slesh_products.py
  f5b2594  S5 — schema + service populate POS variance fields
  18e33d9  S6 — frontend display of POS variance
  ed98938  S7 — three-role security verification record
  (this)   S9 — phase closure documentation

Related design docs:
  docs/slesh-integration-roadmap.md      Parent integration roadmap
  docs/sundance-readiness-roadmap.md     Master Sundance readiness doc
  docs/scanner-architecture.md           Phase 6 scanner subsystem
  docs/scanner-dress-rehearsal-checklist.md  Physical-device checklist
  docs/phase8-s7-verification.md         S7 security verification record
  docs/predictions-module-spec.md        Phase 9 ML model A design
