# XProject — Roadmap

**Status:** Living document · **Last updated:** 2026-04-25 · **Maintainer:** Hesam

This is the single source of truth for everything deferred from v1.0 spec
implementations across all modules. It supersedes scattered `TODO`/`FIXME`
comments in the code and the per-spec §12 "Future scope" sections (those
remain in the specs as design notes, but THIS document is the prioritization).

**Tier system:**

- **Tier 1** — Actionable today. No external blockers. Sundance-relevant.
- **Tier 2** — Real new features. Need spec work. Sundance-relevant if scoped tight.
- **Tier 3** — Dedicated sessions with prerequisites that are present locally.
- **Tier 4** — Blocked on external dependencies (credentials, hardware budget,
  Omar approvals, etc.).

When an item ships, move it to the **Done** section at the bottom.

---

## 🟢 Tier 1 — Actionable today

| # | Item | Module | Effort | Source / Spec ref |
|---|---|---|---|---|
| T1.1 | Settings page (sign out, name, email, language toggle) | new | ~30 min | This roadmap |
| T1.2 | Predictions auto-regen hook in `EventService.update_event` | predictions | ~30 min | predictions-module-spec §6.3 |
| T1.3 | 48h auto-close cron for paused warehouse invoices | warehouse | ~30 min | invoice_service.py:174 |
| T1.4 | Stock-out time computation in Reports per-bar drill-down | reports | ~30 min | aggregator.py:392 |
| T1.5 | Locale-format euros in Reports narrative | reports | ~15 min | templates_happened.py:16 |
| T1.6 | Pending Reviews tile + secondary link layout polish | warehouse | ~30 min | warehouse-module-spec §14 polish backlog |
| T1.7 ✅ | Delete or build orphan stub pages (BarDetailPage, WarehouseInventoryPage) | cleanup | ~30 min | This roadmap |
| T1.8 ✅ | Delete orphan feature stubs (ChatPanel, AlertPanel, EventForm, ScanHistory, RateChart, NarrativeSection, MetricsGrid, ForecastCard, TicketChart) — real implementations live in pages/ | cleanup | ~30 min | This roadmap |
| T1.9 | bar_stock.current_qty INTEGER → NUMERIC migration (Q5 from earlier session) | bar_stock | ~30 min | cascade.py:118 |

**Total Tier 1 effort: ~4 hours, single session.**

---

## 🟡 Tier 2 — Real new features (need spec work)

| # | Item | Module | Effort | Source / Spec ref |
|---|---|---|---|---|
| T2.1 | BarDetailOverlay live data — burn rate, staff, last alert | dashboard | ~3h | BarDetailOverlay.tsx (v1.1 placeholders) |
| T2.2 | Reports — Appendix with raw metrics per bar × product | reports | ~2h | report-module-spec §12 v1.1 |
| T2.3 | Reports — Event Comparison view (≥2 similar events) | reports | ~3h | report-module-spec §12 v1.2 |
| T2.4 | Reports — Manager-facing recap (own-bar data only, no anomalies) | reports | ~3h | report-module-spec §12 v1.3 |
| T2.5 | Audit PDF export of DiscrepancyReport | warehouse | ~2h | warehouse-module-spec §12 |
| T2.6 | Per-bar Manager view of Predictions (filtered) | predictions | ~2h | predictions-module-spec §12 v1.2 |
| T2.7 | PDF export of Predictions (pre-event planning brief) | predictions | ~2h | predictions-module-spec §12 v2.0 |
| T2.8 | Cross-event Predictions comparison view | predictions | ~3h | predictions-module-spec §12 v2.1 |
| T2.9 | Reports — Event P&L (cost entry in Event Create + reconciled actual) | events + reports | ~4h | report-module-spec §12 v2.3 |
| T2.10 | Restock request flow (bar manager via Chat → warehouse runner) | chat + warehouse | ~4h | warehouse-module-spec §12 |
| T2.11 | Supplier analytics dashboard (reliability over time) | warehouse | ~3h | warehouse-module-spec §12 |

**Tier 2 items typically need a 30 min spec addendum before implementation.**

---

## 🔵 Tier 3 — Dedicated sessions, prerequisites present locally

| # | Item | Effort | Prerequisite | Status |
|---|---|---|---|---|
| T3.1 | **MLPredictor — Track 2** | ~4h | Slesh CSVs already profiled (`docs/slesh-data-profiling-report.md`). 5 historical events available locally in `data/`. | Ready to start |
| T3.2 | Model B — live recalibration during events (10-min cycle) | ~3h | Requires Track 2 (MLPredictor) shipped first | Blocked on T3.1 |
| T3.3 | Model C — Owner-override feedback loop | ~3h | Requires T3.1 + T3.2 | Blocked on T3.1, T3.2 |

---

## 🔴 Tier 4 — Blocked on external dependencies

| # | Item | Blocked on | Module |
|---|---|---|---|
| T4.1 | Three-source warehouse reconciliation (POS↔warehouse↔config) | Slesh API credentials from Omar | warehouse |
| T4.2 | Bluetooth scanner integration (Netum) | Omar's hardware budget approval | warehouse |
| T4.3 | Supplier first-class entity migration | Real invoice sample from Omar | warehouse |
| T4.4 | OCR on paper invoices | Decision to add OCR engine to stack | warehouse |
| T4.5 | Weather context integration | Google Weather API keys + decision | predictions |
| T4.6 | Ticketing intelligence (SARIMA on velocity) | Ticket sales data ingestion pipeline | predictions |
| T4.7 | LLM-generated narrative variant for Reports (Pro tier) | Decision to add Anthropic API to stack | reports |
| T4.8 | Reports — ML Accuracy section | Requires T3.1 (MLPredictor shipped) | reports |
| T4.9 | Scheduled email delivery of Reports | Email infra (SES/Postmark/etc.) decision | reports |
| T4.10 | Multi-location warehouses | v2.0 scope — needs new design discussion | warehouse |
| T4.11 | Expiration date tracking + FIFO rotation | v2.0 scope — needs new design discussion | warehouse |
| T4.12 | Case + location barcodes (3-level resolution) | Hardware budget + warehouse zoning labels | warehouse |

---

## 🐛 Known bugs (must fix before next major release)

| # | Bug | Severity | Source |
|---|---|---|---|
| B1 | Pending Reviews tile + secondary link breaks 5-tile grid alignment | Cosmetic | Browser test 2026-04-25 |

---

## ✅ Done (chronological, most recent first)

### 2026-04-25
- T1.7 + T1.8 — orphan stub purge (17 files deleted) + AlertsPage acknowledge bug fix + clean type-check (commit `e56d216`)
- T1.1 — Settings page + roadmap doc + sidebar entry (commit `04e5827`)
- Warehouse Pending Review queue page + RequireAuth race fix (commit `96118bf`)
- Warehouse Phase 3 — camera scanner + invoice flow (commit `6f067c0`)

### 2026-04-24
- Warehouse Phase 2 — frontend dashboard (commit `54277e0`)
- Warehouse Phase 1.5 — 22 REST endpoints (commit `34ed937`)
- Warehouse Phase 1.4 — services + ReconciliationEngine (commit `c3e6bf8`)
- Warehouse Phase 1.2+1.3 — schemas + ORM + repo (commit `09a941c`)
- Warehouse Phase 1.1 — migration (commit `a7ca302`)
- Warehouse spec v1.0 (commit `529d908`)
- Predictions — frontend rewrite with 3 honest states (commit `527718d`)
- Predictions Phase 1 backend — schemas through router (commits `46bdfc5`, `f4bdeac`, `f25fb86`)
- Predictions spec v1.0 + migration (commit `d5c9b32`)

### 2026-04-23 (and earlier)
- Reports module — full v1.0 (8 commits, complete)
- Predictions auto-trigger cron — earlier
- Various event/dashboard/chat work — earlier

---

## How to use this document

1. **Pick from Tier 1 first.** Closes loose ends, no design overhead.
2. **For Tier 2:** write a 30-min spec addendum to the relevant module spec
   before coding. The addendum can be just a section appended to the existing
   spec — keeps a single doc per module.
3. **Tier 3 (Track 2):** dedicated full sessions only. Don't squeeze ML
   training into a 1h slot.
4. **Tier 4:** track Omar conversations + procurement. Don't start until
   the blocker is concretely resolved.
5. **When something ships:** move it to the Done section with the commit hash.

---

## Document history

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-04-25 | Initial compilation. Sourced from spec §12 sections, code TODOs/FIXMEs, audit of stub files, and accumulated session decisions. |
