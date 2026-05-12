# Next Session Handoff — Sundance Data + Catalog Import

**Created:** 2026-05-12 by Hesam + Claude
**Resume context:** mid-Phase-8 Slesh integration

## What was just completed (May 11-12, 2026)

- Phase 6 (Scanner subsystem) — 21 commits, COMPLETE
- Phase 7 (Polish) — 4 commits, COMPLETE
- Slesh integration S1-S3 — cron registered, missing_pos_data fixed
- Sundance 2025 data extracted via Cowork — staged in `data/sundance-2025/`
- 5 CSVs total: 18,069 rows across 5 event dates summer 2025

## Critical discovery from S4 recon

The Slesh integration code (SleshAdapter, slesh_poller, order_ingester,
cascade) is production-grade. The blocker was DATA, not code:
  - Only 2 recipes existed for the tenant (one fabricated test data)
  - 8 of 10 Slesh-sold menu products had no recipe
  - The 502 historical slesh_pos rows landed as parent-only (no children)
    because cascade had no recipe to fan out into

Decision: extract REAL Sundance 2023/2024/2025 history → use as
authoritative catalog source. 2025 done via Cowork on May 12.

## Tasks remaining (in priority order)

### P0 — Extract 2024 + 2023 data
- Open Cowork session
- Use the template at `docs/cowork-prompts/slesh-data-extraction-template.md`
- Run extraction for 2024 → save into `data/sundance-2024/`
- Run extraction for 2023 → save into `data/sundance-2023/`
- Commit each year's CSVs separately

### P0 — Workstream B: Catalog import script
- Build `app/scripts/import_slesh_catalog.py`
- Reads all three years of `catalog.csv` + `stores.csv`
- UPSERTs into `products` and `bars` tables
- Stripping whitespace, classifying Bicchiere as SUPPLY
- Tags imported rows so we know what's seed-from-Slesh vs Omar-modified
- Idempotent: re-runs are safe
- After this, XProject's catalog reflects 3 years of real Slesh history

### P1 — Workstream C: ML training data prep
- The combined `orders_summary.csv` across 3 years = ~50,000+ rows
- Stage for Phase 8 (ML Model A) — don't import to Postgres,
  keep as CSV for pandas pipeline
- See `docs/predictions-module-spec.md` for the original ML design

### Followup items for Omar
- "Will 2026 menu match 2025? Any new products planned?"
- "Recipe decomposition: for each cocktail (Cocktail, Sprtiz, Analcolico,
  etc.), what bottles + quantities?" — needed to make the variance
  signal work
- "Confirm bar→Slesh experience mapping is current"

## Where to start when you resume

1. Read this file
2. `git log --oneline -10` to see recent commits
3. Check `data/` to see what's staged
4. Read `docs/slesh-integration-roadmap.md` for full Slesh context
5. Decide: extract 2024/2023 first, or build import script with just 2025

Suggested order: extract 2024 + 2023 in parallel (Cowork in one window,
import-script work in editor) so import script works against full
3-year dataset on first run.
