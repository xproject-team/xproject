# Sundance 2024 — Known Data Issues

**Last updated:** 2026-05-12
**Status:** Some rows are unreliable; downstream code MUST filter or weight accordingly

## Critical: Aug 4 Slesh data is a copy-paste of Jul 28

Cowork-extracted byte-level comparison confirmed:

  data_04_08_2024/orders/experience-orders.xlsx       =  data_28_07_2024 equivalent  (byte-for-byte)
  data_04_08_2024/stores/Negozi.xlsx                   =  data_28_07_2024 equivalent  (byte-for-byte)
  data_04_08_2024/categorie/Categorie.xlsx             =  data_28_07_2024 equivalent  (byte-for-byte)
  data_04_08_2024/operatori/Operatori-prodotti*.xlsx   =  data_28_07_2024 equivalent  (byte-for-byte)

These 4 Slesh exports for Aug 4 appear to be copy-pastes from Jul 28 made during
folder organization. Only the Prodotti.xlsx (catalog) for Aug 4 has genuine data.

### Affected CSVs in this folder

  orders_summary.csv          4,515 of 21,897 rows are dups of Jul 28
  category_aggregates.csv     1 of 5 rows is a dup
  stores.csv                  7 of 32 rows are dups
  operator_product_mix.csv    ~155 of 861 rows are dups

That's roughly 20% of orders data is duplicate.

### Unaffected files (Aug 4 data is genuine)

  catalog.csv                 Aug 4 catalog has real numbers (lower sales)
  attendance.csv              From manual workbook; Aug 4 = 1,227 people (real)
  beverage_inventory.csv      From manual workbook; not affected
  drink_recipes.csv           Season-level data; not affected
  season_budget.csv           Season-level data; not affected

## How downstream code should handle this

Two options:

  Option A (recommended for ML training):
    Filter event_date = '2024-08-04' from orders_summary, stores, operators,
    category_aggregates. Use catalog.csv + attendance.csv for Aug 4 only.

  Option B (recommended for catalog-import):
    All 5 dates' catalog.csv data is genuine; safe to use unfiltered.

## Other data quality observations

1. CARICO_BAR sheet header says "Consumo 14/06" but Jun 16 was the first event.
   Source typo. Beverage_inventory.csv has been corrected to event_date 2024-06-16.

2. Jul 14 refunds (rimborsi) file was misfiled into data_30_06_2024 folder.
   We don't extract rimborsi (PII-heavy), but flagged for owner awareness.

3. data_28_07_2024 is missing Operatori-ordini-annullati and
   Operatori-prodotti-annullati files. Only confermati data available.
   Annullati rows are 0 for Jul 28 in our extracted CSVs.

4. attendance.csv shows ticket_count + free_entry as float (e.g. 1381.0).
   pandas-default behavior; safe to int-cast in downstream code.

5. data_default folder exists but is empty (template skeleton). Skipped.

## Action items for the data owner (Omar)

  [ ] Confirm whether Aug 4 Slesh exports exist elsewhere (real ones)
  [ ] If yes, re-stage data/sundance-2024/ from the corrected source
  [ ] Verify the Jul 28 vs Aug 4 catalog sales delta is real
      (Jul 28: 1,647 people; Aug 4: 1,227 people — Aug 4 was smaller)

## Re-extraction notes

Source location: ~/Desktop/2024/SUNDANCE/
Extraction date: 2026-05-12
Extraction tool: Claude Cowork via two-phase prompt
  (discovery + Phase 2A canonical + Phase 2B bonus)
