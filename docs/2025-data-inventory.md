# 2025 Sundance Data Inventory

**Date:** June 1, 2026 (S1 of e2e validation build)
**Source:** ~/Desktop/2025/

## Events available

| Folder | Date | Status |
|--------|------|--------|
| data_15_06_2025 | 15 June 2025 | Full export, used for simulator design |
| data_29_06_2025 | 29 June 2025 | Full export |
| data_13_07_2025 | 13 July 2025 | Full export |
| data_27_07_2025 | 27 July 2025 | Full export |
| data_03_08_2025 | 3 August 2025 | Full export |

All 5 events follow the same folder structure (1-ricariche, 2-ordini_bracciali, 3-prodotti, 4-categorie, 5-negozi, 6-operatori, rimborsi). 17 MB total, 78 files. Consistent format across events.

## Per-event folder structure

| Folder | Contents | Used by simulator? |
|--------|----------|--------------------|
| 1-ricariche | Wristband top-ups | No (not transactions) |
| **2-ordini_bracciali** | **Per-order transactions** ⭐ | **Yes — the replay stream** |
| **3-prodotti** | **Product catalog + prices + categories** ⭐ | **Yes — for unit prices** |
| 4-categorie | Categories catalog | No (info in 3-prodotti) |
| 5-negozi | **Per-bar aggregates** | Yes — for bar inventory |
| 6-operatori | Per-operator breakdowns | No (not needed for simulator) |
| rimborsi | Refunds | No (defer; could matter later) |

## Key file: experience-orders-*.xlsx

The order stream. For 15_06_2025: 4,224 rows × 18 cols, 1.2 MB.

**Important columns:**
- `ID` — Mongo ObjectID (UTC seconds encoded in first 8 hex chars)
- `Codice` — sequential within event: "el-0", "el-1", ... USE FOR SORTING
- `Data ed ora` — "DD/MM/YYYY HH:MM" (Europe/Rome local, minute resolution)
- `Negozio` — bar NAME (no shop_id in export!) Trailing spaces present
- `Prodotti` — comma-separated product names (1+ products per row)
- `Totale` — total euros for the order (sum of product prices)
- `Stato` — always "completed" (Slesh pre-filtered)
- `Tipologia` — always "experience" (vs ricariche/top-ups)

**Data shape:**
- 100% completed status — no cancellations to filter
- 43.5% of rows are multi-product orders
- Totale is in whole euros (not cents) — must × 100 on ingestion
- Minute-resolution timestamps; use `Codice` for sub-minute ordering

## Key file: Prodotti-categoria-*.xlsx

The catalog. 32 rows × 6 cols for 15_06_2025.

**Columns:**
- `Prodotto` — product name (matches Negozio names in orders file)
- `Prezzo` — **unit price in euros** ⭐
- `Totale` — total units sold this event
- `beverage`, `Food`, `Guardaroba` — one-hot category flags ⭐

**Why this is gold:**
1. Unit prices let us split multi-product orders accurately
2. Native Slesh category columns (beverage/food/guardaroba) — no
   fuzzy categorization needed for the simulator
3. The categories map to our 4+1 display buckets:
     beverage → beer / cocktails / premium_cocktails / wine (refine
                by NAME within beverage, e.g. "Cocktail Super premium")
     Food → food
     Guardaroba → other (cup deposit)

## Bars per event (15_06_2025)

| Bar | Orders | Revenue (€) | Type |
|-----|--------|-------------|------|
| Cocktail Bar  | 2,715 | 36,160 | drinks (main) |
| Beer Bar | 832 | 6,574 | drinks |
| Malandrino | 221 | 2,113 | food |
| Focacceria  | 211 | 1,824 | food |
| Figo  | 124 | 1,128 | mixed |
| La Nina | 102 | 1,304 | food |
| Gelateria | 18 | 78 | gelato |
| Guardaroba | 1 | 3 | cloakroom (deposits) |

Bar names have trailing spaces in the source. Normalize on ingestion.

## Products (15_06_2025)

32 unique products across all bars. Split:
- **Beverages:** Acqua, Analcolico, Bottiglia Vino, Cocktail, Cocktail Premium, Cocktail Super premium, Nastro Azzurro, Raffo, Soft Drink, Sprtiz
- **Food:** Arancine, Bu Chicken, Bu Pork, Bu Veggy, Burger, Calamari e Moscardini, Cartoccio Misto, Mortadella, Nachos, Patatina Grande, Patatina Media, Polletti, Porchetta, Prosciutto, Pulled Chicken Burger, Pulled Pork Burger, Pulled Salmon Burger, Gelato
- **Deposits:** Bicchiere (cup), Guardaroba (cloakroom)

## Price math validation

Tested unit-price × quantity = Totale on 15 multi-product rows:
- 14 ✅ exact match
- 1 ❌ off by €2 ("Nastro Azzurro x2 + Bicchiere x2": computed €14 vs actual €12)

Hypothesis: Slesh applies promo discounts at the order level (e.g.
"2 beers for €10 instead of €12"). The Prodotti-categoria file
shows LIST price, not effective price. Promo math is not exposed
in the export.

**Mitigation:** the simulator uses list-price × quantity. Track
"price_mismatch_total" as a diagnostic; if <2% of revenue, ignore.

## Open questions (post-simulator)

1. Does the live Slesh API return per-order discounted price, or
   list price like the export? If the former, the simulator and
   live diverge slightly — investigate before relying on the
   simulator for revenue accuracy.
2. Cauzioni (cup deposit) refunds — currently ignored. Real Sundance
   2026 will have these; decide whether they generate a "negative
   transaction" or are tracked separately.
3. ricariche (top-ups) — not in current scope. They precede orders;
   the wristband must be loaded before a guest can order. Worth
   modeling for full realism, but skip for first simulator iteration.

## Decision: which event to simulate first

**15_06_2025** for the first simulator run, because:
- Largest event by orders (4,224)
- All 8 bars active (good name-matching test)
- All 32 products represented (good catalog test)
- 10-hour duration (rich timeline to replay)
- Clean export (verified above)

After 15_06 works, run the other 4 events as a regression suite.
