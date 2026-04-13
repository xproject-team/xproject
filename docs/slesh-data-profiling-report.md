# Slesh Data Profiling Report

**Date:** 2026-04-13
**Author:** Hesam (with Claude)
**Sample event:** Sundance — 03/08/2025 (most recent of 5 local event folders)
**Source files:** `data/2025/SUNDANCE/data_03_08_2025/` (gitignored)
**Decision binding:** This report drives backend schema design and the Slesh API conversation.

---

## 1. Executive Summary

We profiled all 9 data folders Slesh exports per event. **Three findings reshape our architecture:**

1. **Slesh exports are mostly aggregated summaries**, not raw operational data. The richest raw data is in `2-ordini_bracliali` (3,187 transactions) and `1-ricariche` (2,140 top-ups). Other folders contain post-event totals only.
2. **Slesh has no concept of product tiers (B/S/P/U)** — that classification must originate in our system, configured by Omar at event setup.
3. **The `rimborsi` (refunds) folder contains extreme PII** (IBAN, tax ID, home addresses). **Decision: refunds are OUT OF SCOPE for XProject.** Slesh handles refund processing; we display aggregate stats only.

**Architectural conclusion:** XProject is a **complement** to Slesh, not a replacement. Slesh = transaction/payment system of record. XProject = operational intelligence layer on top.

---

## 2. Per-Folder Inventory

### 2.1 `1-ricariche` — Top-ups (wallet recharges)

- **Master file:** 2,140 rows × 21 columns. Real-world transactions.
- **Daily split file:** 3 rows × 6 columns. Aggregated per day.
- **PII level:** HIGH — names, emails, Stripe payment IDs.
- **Quality:** 23.6% rows have NULL Stripe info (cash top-ups at cash desks).
- **Multi-day pattern:** Top-ups happen days BEFORE the event (Sundance 03/08 had pre-event top-ups on 28/07 and 30/07).
- **Architecture role:** Read for analytics (volume, payment-mix, fraud detection); never expose customer PII in our UI.

### 2.2 `2-ordini_bracliali` — Orders (drink/food sales)

- **File:** 3,187 rows × 18 columns. Core transaction dataset.
- **PII level:** HIGH — names, emails, customer demographics.
- **CRITICAL data shape problem:** `Prodotti` column is a comma-separated string ("Acqua, Acqua, Bicchiere, Bicchiere") — NOT a structured line-item list. Splitting/counting requires a fragile parser.
- **Workaround discovered:** `6-operatori/Operatori-prodotti-confermati` reconstructs per-product counts via per-operator pivot — usable for retroactive analytics.
- **Slesh API requirement:** Confirm if API returns proper line items (one row per product sold).

### 2.3 `3-prodotti` — Products

- **3 files**, all aggregated post-event summaries. No real product catalog.
- **19 products total** in this event.
- **Missing:** product tiers, recipes (bottle-to-drink conversion), per-bar allocation, opening stock per bar.
- **Architecture implication:** Product catalog originates in OUR system (Event Create form sections 3, 4, 5).

### 2.4 `4-categorie` — Categories

- 2 macro-categories only: `beverage` and `Food`.
- Per-product breakdown also provided (19 rows).
- **No B/S/P/U tier system** in Slesh. Tier classification is OUR system's invention.

### 2.5 `5-negozi` — Bars / Cash desks

- **3 negozi for Sundance 03/08:** Cocktail Bar (€32k revenue), Focacceria (€2k), Malandrino (€2.6k).
- **Cocktail Bar = 92% of revenue.**
- **Focacceria + Malandrino = food vendors.** Slesh treats bars and food vendors identically — `negozio` is a generic concept.
- **v2.1 implication:** Splitting "Food Truck" into a separate module may be over-engineered. Reconsider with Omar.

### 2.6 `6-operatori` — Staff

- 5 files. Two operator types identified:
  - **Cashiers** (`S2025-cassa-N@slesh.it`): handle wallet top-ups.
  - **Bartenders** (`S2025_cocktailbar-N@slesh.it`): handle drink orders.
- **Per-operator-product pivot** in `Operatori-prodotti-confermati` (24 columns) — gives us the line-item view that `2-ordini_bracliali` doesn't.
- **Cancelled orders tracked separately** (`Operatori-ordini-annullati`) — anomaly source.

### 2.7 `7-bracciali` — Wristbands (EMPTY)

- No `.xlsx` files. Only Slesh dashboard JPG.
- Wristband data is NOT exported as flat files.
- **Conclusion:** Per-wristband data only available via API.

### 2.8 `8-utenti` — Users (EMPTY)

- Same as wristbands. Only available via API.
- **Conclusion:** Customer-level analytics requires the Slesh API.

### 2.9 `rimborsi` — Refunds

- 71 rows × 17 columns.
- **EXTREME PII:** IBAN, BIC/SWIFT, Codice Fiscale (Italian tax ID), full home addresses, names, emails.
- **DECISION:** OUT OF SCOPE for XProject. Aggregate stats only.

---

## 3. PII Inventory & Handling Rules

| File | PII Fields | Handling Rule |
|---|---|---|
| 1-ricariche | name, email, Stripe IDs | Ingest for analytics; never display in UI; pseudonymize on export |
| 2-ordini_bracliali | name, email, gender | Same as above |
| rimborsi | IBAN, tax ID, address, name, email | **NEVER ingest. Out of scope.** |
| All others | None | Safe |

**Cross-cutting rules:**
- Raw exports stay in `data/` (gitignored).
- Database stores hashed user IDs, never raw emails or names.
- Backend API exposes aggregates, never row-level PII.
- Logs and exports include opt-in for Owner; never accessible to managers/staff.

---

## 4. Architecture Implications

### 4.1 Slesh as Transaction Stream, Not Source of Truth

XProject's data model has TWO origin points:

- **Configured in XProject (Owner enters):** Bar list, product catalog, recipes, initial stock allocation, product tiers (B/S/P/U).
- **Ingested from Slesh (live or batch):** Transactions, top-ups, operator activity, cancellations.

The two streams JOIN on: `negozio` (bar name) + `prodotto` (product name) + `operatore` (staff email).

### 4.2 Backend Schema Sketch (Initial)

XProject-owned tables (Owner configures):
- `tenants` (already built)
- `users` (already built — Owner, Manager, Bartender, Warehouse roles)
- `venues` (already built)
- `events` (already built)
- `bars` — to add (per-event bar list, Slesh `negozio` mapping)
- `products` — to add (Owner-configured catalog with tier, price, recipe)
- `recipes` — to add (bottle-to-drink conversion)
- `bar_inventory` — to add (per-bar opening stock)

Slesh-ingested tables (read from API/exports):
- `transactions` — to add (one row per order, references bar+operator)
- `transaction_items` — to add (one row per product-in-order — reconstructed from operator pivot if API returns string blob)
- `topups` — to add (wallet recharges)
- `operators` — to add (Slesh staff roster, separates cashier/bartender by role)
- `cancellations` — to add (cancelled orders, anomaly source)

Out of scope:
- `refunds` table — we do not store this data.

### 4.3 The Tier Classification Problem

Slesh has no B/S/P/U tier. Three resolution options for Omar:
- Manual: Omar tags each product with tier in Event Create form.
- Inferred: Backend assigns tier based on price brackets (e.g., < €5 = Basic, €5-10 = Standard, €10-15 = Premium, > €15 = Ultra).
- Removed: Drop tier from MVP if not strongly required.

### 4.4 The "Comma-Separated Products" Problem

The orders file's `Prodotti` column blocks per-product analytics in real-time. Two solutions:
- **Preferred:** Slesh API returns proper line items per order. Confirm via email.
- **Fallback:** Build a parser using the per-operator pivot data as a reconstruction reference.

---

## 5. Open Questions for Slesh API

These go in the bilingual Slesh email:

1. Does the API expose **per-product line items per order** (not the comma-separated string we see in exports)?
2. Does the API support **webhook push** for real-time transactions, or polling only?
3. Polling rate limit, if no webhook?
4. Authentication: API key, OAuth, per-event token?
5. Sandbox/test environment available before April demo?
6. Data freshness latency (immediate vs batched 5-10 min)?
7. **Wristband endpoint**: per-wristband balance, top-up history, transaction log?
8. **User endpoint**: per-customer profile (without PII we don't need)?
9. **Refund aggregates endpoint**: counts/totals only, no IBAN/tax ID?
10. Historical access: backfill past Sundance events via API, or only Excel export?
11. Where do **product tiers** live in Slesh, if anywhere?
12. Is there a **product catalog endpoint** that returns the active catalog per event?

---

## 6. Open Questions for Omar

To finalize during a strategic call:

1. **Tier classification:** manual entry, inferred from price, or drop from MVP?
2. **Food trucks vs bars:** treat as same entity (Slesh-aligned) or split into separate UI module (v2.1 spec)?
3. **Wallet balance:** is per-customer wallet balance a feature Omar wants visible in XProject, or Slesh-only?
4. **Refunds confirmation:** confirm Slesh handles refund processing end-to-end, XProject only shows aggregate stats?
5. **Cancellation alerts:** should cancelled orders trigger an alert in our system?
6. **Discrepancy of 5 vs 10 events:** which other 5 Sundance event folders exist?

---

## 7. Next Steps

1. ✅ Profiling complete (this document).
2. → Write bilingual Slesh email using questions in Section 5.
3. → Schedule Omar call to resolve questions in Section 6.
4. → Design backend migrations for the new tables in Section 4.2.
5. → Build Dashboard with placeholder data while Slesh API access pending.

---
