# Warehouse Module — Specification v1.0

**Status:** Draft · **Owner:** Hesam · **Last updated:** 2026-04-23 · **Target:** Sundance June 2026

This document is the single source of truth for the XProject Warehouse module. It supersedes Section 10 of the Backend Architecture Bible where they disagree.

**When this spec and any older document disagree, this spec wins.**

---

## 1. Why this module exists

Omar articulated the Warehouse module's purpose in one sentence:

> *"When the truck comes to deliver bottles, the driver gives an invoice. I want to know: if I ordered 200 bottles of vodka, after scanning all of them, does it really come to 200 or not? Because I don't trust the deliveries."*

That is the entire module. Everything else — inventory tracking, allocations, dashboards — exists to support this single loop:

**Expected** (what Omar ordered, typed into the system from the paper invoice)
→ **Actual** (what physically arrived, scanned in with the camera)
→ **Discrepancy** (the difference, visible to Omar before the driver leaves)

Three design pillars drive every decision:

1. **Supplier fraud detection is the hero feature.** Generic inventory tracking is a supporting concern, not the headline. The invoice reconciliation loop lives on the main page; everything else serves it.
2. **Camera-first scanning with manual entry fallback.** The default experience is "open the screen, point the camera at a bottle, it's scanned." When camera fails or a product has no barcode, the user types. Never a dead-end.
3. **Data model reflects reality, not bookkeeping convenience.** Warehouse inventory is tenant-scoped (not event-scoped); events *allocate* from the warehouse. This matches how physical warehouses actually work.

---

## 2. What we are NOT building in v1.0

Dropped from Backend Bible §10 scope:

| Old scope | Status in v1.0 | Why dropped |
|---|---|---|
| Bluetooth hardware barcode scanners (Netum €35-50) | ❌ deferred | Budget unapproved; camera-based scanning via `html5-qrcode` is sufficient and hardware-free |
| QR label printer + XProject-printed labels | ❌ deferred | Relies on printer purchase; we read supplier-issued barcodes (EAN/UPC), not print our own |
| Three-level barcode resolution (product/case/location) | ❌ simplified to 2 | Location barcodes require physical warehouse zones with labels. v1.0 assumes one warehouse location per tenant. |
| Three-source reconciliation (warehouse ↔ POS ↔ event config) | ❌ deferred | POS source is blocked on Slesh credentials. Our reconciliation compares invoice vs scan (two-source). |
| OCR on paper invoices | ❌ v1.1 | Manual invoice entry is 30 seconds; OCR engine is an infrastructure hazard not justified yet |
| Supplier first-class entity | ⏸ DEFERRED pending evidence | See §4.X — awaiting real invoice sample from Omar before designing the schema |
| Restock request workflow (Chat integration) | ❌ v1.1 | Ships after Chat module deeper integration |
| Audit PDF export | ❌ v1.1 | Reports module's PDF renderer can be extended later |

We also explicitly reject any UI framing that promises features we haven't built. No "ML-powered fraud detection" labels. No "3-source verification" text. The system does exactly what the spec says: compares invoice vs scan, flags discrepancies.

---

## 3. What Omar sees — three user journeys

Access: Owner, Warehouse Keeper, Manager, Bartender — each sees a role-aware subset (see §3.5).

### 3.1 Journey A — Owner creates a delivery invoice (before truck arrives)

Omar received a paper invoice from the supplier: "200× Vodka, 50× Gin, 30× Rum, arriving Friday."

1. Omar clicks **"New Delivery"** on `/warehouse`
2. Form opens:
   - Supplier name (freetext for v1.0)
   - Expected arrival date
   - Line items (add rows): product dropdown + expected quantity + unit price
   - Optional "miscellaneous" freetext rows for weird items not in catalog
3. Omar reviews the running total (auto-computed: sum of qty × price)
4. Clicks **Save** → invoice row created with `status = EXPECTED`

**Visible outcome:** invoice appears on the `/warehouse` page in a "Pending Deliveries" strip. Ready for when the truck arrives.

### 3.2 Journey B — Staff receives the delivery (scan session)

Friday morning, the truck arrives. Marco (warehouse keeper) is on shift.

1. Marco opens `/warehouse` on his phone → taps the pending invoice card
2. Page opens the **Scan Session screen** — progress bars per expected item ("Vodka 0/200", "Gin 0/50", "Rum 0/30")
3. Marco taps **"Start Scanning"** → camera activates (prompts for permission if first time)
4. Points camera at bottle → barcode read → product identified → scan recorded → progress bar increments
   - Green ✓ if product is on the invoice
   - Yellow ⚠ with "Pending Review" tag if product is NOT on the invoice
   - Red ✗ if unreadable or product unknown (fallback to manual entry)
5. Marco scans until all bottles are done — or gets interrupted
6. Session can be **paused** — state saved, progress bars remember counts
7. When all done, Marco taps **"Close Session"**

**Visible outcome:** the screen transitions to Journey C.

### 3.3 Journey C — Discrepancy Report (the moment of truth)

After session close, the system computes expected vs scanned:

- **Vodka:** invoice said 200, scanned 187 — **SHORT 13 bottles** 🚨
- **Gin:** invoice said 50, scanned 50 — ✅ match
- **Rum:** invoice said 30, scanned 32 — 🎉 2 extra (needs Owner review)
- **Pellegrino sparkling** (not on invoice): 12 scanned — ⚠ **unexpected, needs approval**

Omar opens the report on his phone:
- Top banner: "**Discrepancy detected** — Vodka short by 13 bottles (€156 value)"
- Per-line breakdown with color coding
- Actions: **"Accept as-is"** / **"Dispute with supplier"** / **"Log for later"**
- If **Dispute**: discrepancy frozen, driver can be challenged with evidence (who scanned what, when, what was expected)

**Visible outcome:** invoice `status` transitions to `VERIFIED` (all matched), `DISCREPANCY` (mismatch logged), or `DISPUTED` (formal dispute opened).

### 3.4 Owner Dashboard layout

Sticks to the Q3-locked scope: **4 KPI tiles + product grid + activity feed**.

**Top strip — 4 KPI tiles:**
1. **Total Items in Warehouse** — sum of `current_qty` across all products
2. **Products at Risk** — count where `current_qty < threshold` (threshold = 20% of historical usage)
3. **Active Allocations** — bottles reserved for live/upcoming events
4. **Pending Reviews** — unexpected scans awaiting Owner approval + unresolved discrepancies

**Second strip — Pending Deliveries (if any):**
- Horizontal scrollable list of invoices with `status IN (EXPECTED, SCANNING, PAUSED)`
- Each card: supplier name, expected date, progress bar if scanning, "Open" button

**Main area — Product Inventory Grid:**
- Searchable/filterable table: Product · Category · Current Qty · Allocated · Available · Last Movement
- Sortable; default sort is "at-risk first" (lowest available qty)

**Side panel — Activity Feed:**
- Last 20 scan events in reverse-chron order
- Format: `14:32 · Intake · 12× Bombay Gin · Marco (warehouse keeper)`
- Role badge on each row — the audit trail Omar asked for

**Red banner (conditional):**
- Appears only when there are urgent items: *"3 unresolved discrepancies, 2 products at risk"*
- Click expands to action list

### 3.5 Role-aware UI

Per Q4b decision — the scanner screen shows different buttons by role. Backend also enforces (not just cosmetic).

| Role | Buttons visible | Primary default | Notes |
|---|---|---|---|
| **Owner** | Intake · Dispatch · Return · Adjustment · **Inspect** | Inspect | Emergency verification use case |
| **Warehouse Keeper** | Intake · Dispatch · Return | Intake | Primary shift workflow |
| **Manager** | Dispatch (to own bar) · Return (from own bar) | Dispatch | Bar-scoped via FK |
| **Bartender** | **Inspect** only | Inspect | Read-only — "did I get the right bottle?" |

---

## 4. Data model

### 4.1 `delivery_invoices` table (hero entity)

Per Q6 decision — multi-product flexible with miscellaneous freetext rows. Line items live in a separate `invoice_items` table.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK → tenants.id CASCADE | |
| `invoice_number` | varchar(128) nullable | From supplier's paper invoice (not always provided) |
| `supplier_name` | varchar(255) | **See §4.X — deferred** |
| `expected_arrival_date` | date | |
| `status` | enum | `EXPECTED`, `SCANNING`, `PAUSED`, `VERIFIED`, `DISCREPANCY`, `DISPUTED`, `CLOSED` |
| `scan_started_at` | timestamptz nullable | Set when first scan happens |
| `scan_closed_at` | timestamptz nullable | Set on close-session |
| `closed_by` | UUID FK → users.id nullable | Who pressed "Close" |
| `notes` | text nullable | Freetext Owner notes |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Indexes:**
- `(tenant_id, status)` — hot dashboard query
- `(tenant_id, expected_arrival_date DESC)` — chronological list
- `(tenant_id, supplier_name)` — supplier history lookup (enables the future v1.1 supplier migration)

### 4.2 `invoice_items` table (line items per invoice)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | |
| `invoice_id` | UUID FK → delivery_invoices.id CASCADE | |
| `product_id` | UUID FK → products.id nullable | **NULL when row is "miscellaneous freetext"** |
| `miscellaneous_description` | varchar(255) nullable | Populated when `product_id IS NULL` |
| `expected_qty` | numeric(12,2) | |
| `unit_price_cents` | integer nullable | Per Q9 — optional but encouraged |
| `line_total_cents` | integer nullable | Computed: `expected_qty × unit_price_cents`, stored for quick totals |
| `created_at` / `updated_at` | timestamptz | |

**Check constraint:** `product_id IS NOT NULL OR miscellaneous_description IS NOT NULL` — every line must describe *something*.

### 4.3 `warehouse_inventory` table (tenant-scoped per Q2)

One row per (tenant, product). NOT event-scoped. The warehouse has stock independently of which events might use it.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | |
| `product_id` | UUID FK → products.id | |
| `current_qty` | numeric(12,2) | Physical count, updated on every scan |
| `low_stock_threshold` | numeric(12,2) nullable | For "At Risk" KPI; default 10 units if NULL |
| `last_movement_at` | timestamptz nullable | Last time this row changed |
| `created_at` / `updated_at` | timestamptz | |

**Unique constraint:** `(tenant_id, product_id)` — one inventory row per product per tenant.

### 4.4 `warehouse_scans` table (append-only audit trail)

Every scan is a row. Never deleted. Powers the activity feed and discrepancy evidence.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | |
| `scan_type` | enum | `INTAKE`, `DISPATCH`, `RETURN`, `ADJUSTMENT`, `INSPECT`, `CONSUMED` |
| `invoice_id` | UUID FK → delivery_invoices.id nullable | SET for INTAKE during a scan session; NULL otherwise |
| `product_id` | UUID FK → products.id nullable | NULL when barcode unrecognized |
| `barcode_raw` | varchar(255) nullable | What the camera actually read — for debugging/audit |
| `qty` | numeric(12,2) | Usually 1.0 for single-bottle scans; higher for case scans |
| `event_id` | UUID FK → events.id nullable | SET for DISPATCH/RETURN/CONSUMED (event-scoped); NULL otherwise |
| `bar_id` | UUID FK → bars.id nullable | SET for DISPATCH (destination) and CONSUMED (source) |
| `is_unexpected` | boolean default false | TRUE when INTAKE scan is for product NOT on the invoice (Q7) |
| `pending_review` | boolean default false | TRUE when needs Owner action; flipped to FALSE on approve/reject |
| `scanned_by_user_id` | UUID FK → users.id | Who scanned |
| `scanned_by_role` | enum | **Snapshot at scan time** — owner/manager/bartender/warehouse_keeper |
| `scanned_at` | timestamptz default now() | |

**Indexes:**
- `(tenant_id, scanned_at DESC)` — activity feed
- `(tenant_id, invoice_id)` — all scans for one invoice session
- `(tenant_id, event_id, bar_id)` — dispatch history per bar per event
- `(tenant_id, pending_review)` where pending_review = true — fast lookup for the pending queue

### 4.5 `warehouse_allocations` table (events reserving from warehouse)

When an event is configured, its expected bar_stock totals are "reserved" in the warehouse. Prevents double-booking across overlapping events.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | |
| `event_id` | UUID FK → events.id CASCADE | |
| `product_id` | UUID FK → products.id | |
| `reserved_qty` | numeric(12,2) | Qty the event has reserved |
| `dispatched_qty` | numeric(12,2) default 0 | How much has physically moved to bars (incremented by DISPATCH scans) |
| `created_at` / `updated_at` | timestamptz | |

**Unique constraint:** `(tenant_id, event_id, product_id)`.

**Invariant enforced in service layer:** `sum(reserved_qty WHERE event active) <= warehouse_inventory.current_qty` per product. Service prevents over-allocation.

### 4.X Supplier modeling — DEFERRED

**Status: INTENTIONALLY NOT DECIDED IN v1.0 SPEC.**

Omar to provide a real supplier invoice sample. Decision between (a) freetext only, (b) first-class suppliers table, (c) hybrid migration path will be made when we see the actual evidence.

**For v1.0 migration purposes:** `delivery_invoices.supplier_name` is a `varchar(255)` column populated by freetext entry. This leaves both paths open:
- **If we pick freetext:** nothing changes
- **If we pick first-class table:** future migration adds `suppliers` table + `delivery_invoices.supplier_id` FK; backfill script populates from distinct `supplier_name` values

No v1.0 code is locked in before seeing evidence. When Omar sends the invoice sample, we write an addendum to this section with the final decision.

---

## 5. Invoice lifecycle (state machine)

Per Q8 decision — partial close allowed.

```
         [EXPECTED]
             │
        First scan
             ▼
        [SCANNING]
          │    │
  Pause   │    │  Close
          ▼    ▼
        [PAUSED]      [reconciliation]
          │             │    │    │
       Resume         100%  ≠  contested
          │             │    │    │
          ▼             ▼    ▼    ▼
        [SCANNING]  [VERIFIED][DISCREPANCY][DISPUTED]
                        │    │    │
                     Owner reviews / closes
                        │    │    │
                        ▼    ▼    ▼
                      [CLOSED]
```

**Transitions:**
- `EXPECTED → SCANNING`: first scan against this invoice
- `SCANNING → PAUSED`: user taps "Save & Exit" (48h grace before auto-close)
- `PAUSED → SCANNING`: user resumes session
- `SCANNING → VERIFIED`: all expected items scanned with no extras
- `SCANNING → DISCREPANCY`: close with mismatch (short or unexpected extras)
- `DISCREPANCY → DISPUTED`: Owner formally disputes with supplier
- `DISCREPANCY → CLOSED`: Owner accepts as-is (absorbs the loss)
- `DISPUTED → CLOSED`: supplier resolves (credit issued, replacement sent, etc.)
- `VERIFIED → CLOSED`: automatic after 24h or immediate if Owner taps "Archive"

**Auto-close safety:** `PAUSED` invoices older than 48h auto-transition to `DISCREPANCY` with current scan counts. Prevents sessions from being abandoned indefinitely.

---

## 6. Camera-based scanning (frontend)

Per Q1 + Q4b decisions.

### 6.1 Library: `html5-qrcode`

- BSD-licensed, actively maintained
- Supports EAN-13, UPC-A, QR, Code128 — all common supplier barcodes
- Browser-native getUserMedia, no plugins
- Permission prompt on first use; graceful fallback if denied

### 6.2 Flow

1. User taps "Start Scanning"
2. Request camera permission if not granted
3. On grant: camera preview opens, barcode detection runs continuously
4. On detection: vibrate + beep + show confirmation chip → record scan → continue
5. On permission denial: show manual entry form with helpful message
6. On camera error (hardware busy, insufficient light, etc.): show error + manual entry fallback

### 6.3 Manual entry fallback

Always available via a "Type Instead" button next to the camera.

Form fields:
- Product (dropdown, type-ahead search through product catalog)
- Quantity (default 1)
- Submit adds a scan with `barcode_raw = NULL`, `product_id` from dropdown

### 6.4 Unexpected scan handling (per Q7)

When scan matches a product NOT on the current invoice's expected items:
1. Product is identified normally (barcode → product_id)
2. Scan recorded with `is_unexpected = true` AND `pending_review = true`
3. Scanner shows yellow banner: *"This product isn't on the invoice — logged for Owner review"*
4. Scan continues — does NOT block session
5. Appears in Owner's "Pending Reviews" KPI tile + Discrepancy Report

---

## 7. Reconciliation engine

Pure function: `compute_discrepancy(invoice) -> DiscrepancyReport`

```python
class DiscrepancyLine(BaseModel):
    product_id: UUID | None
    product_name: str
    expected_qty: Decimal
    scanned_qty: Decimal
    delta: Decimal  # scanned - expected
    status: Literal["match", "short", "extra", "unexpected"]
    unit_price_cents: int | None
    value_delta_cents: int | None  # delta * unit_price

class DiscrepancyReport(BaseModel):
    invoice_id: UUID
    computed_at: datetime
    lines: list[DiscrepancyLine]
    total_expected_cents: int | None
    total_scanned_value_cents: int | None  # based on scanned qty × unit_price
    total_delta_cents: int | None
    has_shortage: bool
    has_unexpected: bool
    overall_status: Literal["match", "discrepancy", "dispute_opened"]
```

**Computed every time invoice close is attempted.** Persisted as the final state alongside the scan history.

---

## 8. REST endpoints

Base: `/api/v1/warehouse`

### Invoice management
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/invoices` | Owner | Create new delivery invoice |
| GET | `/invoices` | Owner, Warehouse | List invoices filterable by status |
| GET | `/invoices/{id}` | Owner, Warehouse | Detail with line items + live scan progress |
| PATCH | `/invoices/{id}` | Owner | Edit before scanning starts (status=EXPECTED only) |
| POST | `/invoices/{id}/start-scan` | Owner, Warehouse | Transition EXPECTED → SCANNING |
| POST | `/invoices/{id}/pause` | Owner, Warehouse | Transition SCANNING → PAUSED |
| POST | `/invoices/{id}/resume` | Owner, Warehouse | Transition PAUSED → SCANNING |
| POST | `/invoices/{id}/close` | Owner, Warehouse | Compute discrepancy, transition to VERIFIED/DISCREPANCY |
| POST | `/invoices/{id}/dispute` | Owner | DISCREPANCY → DISPUTED with reason |
| POST | `/invoices/{id}/archive` | Owner | VERIFIED/DISCREPANCY/DISPUTED → CLOSED |
| GET | `/invoices/{id}/discrepancy-report` | Owner | Returns DiscrepancyReport JSON |

### Scanning
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/scans` | Role-aware | Record a scan. Body: `{scan_type, barcode_raw?, product_id?, qty, invoice_id?, event_id?, bar_id?}` |
| GET | `/scans` | Owner | Activity feed. Filterable by scan_type, date range, user, role |
| GET | `/scans/pending-review` | Owner | Unexpected scans awaiting approval |
| POST | `/scans/{id}/approve` | Owner | Flip pending_review=false, accept as bonus stock |
| POST | `/scans/{id}/reject` | Owner | Flip pending_review=false, reverse the inventory impact |
| POST | `/barcode/resolve` | Any role | Given raw barcode, return product match or "unknown" |

### Inventory read views
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/inventory` | Owner, Warehouse | Product grid with current_qty + allocated_qty + available_qty |
| GET | `/inventory/kpis` | Owner | 4 KPI tile values |
| GET | `/inventory/{product_id}` | Owner, Warehouse | One product's detail: stock, allocations, recent scans |

### Allocations
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/allocations/event/{event_id}` | Owner | What the event has reserved |
| PATCH | `/allocations/event/{event_id}` | Owner | Update reserved_qty per product |

**Role enforcement per endpoint is matrix-based** — spec §3.5 defines visibility, backend `require_role()` dependencies enforce. Owner bypasses every restriction.

---

## 9. Frontend contract

### 9.1 Routes

- `/warehouse` — Owner dashboard (KPIs + pending deliveries strip + product grid + activity feed)
- `/warehouse/invoices/new` — Invoice creation form
- `/warehouse/invoices/:id` — Invoice detail with scan session UI
- `/warehouse/scan` — Quick-scan screen (Owner's "inspect" entry point; staff's default)
- `/warehouse/pending-review` — Owner's pending-review queue

### 9.2 Hooks (`features/warehouse/useWarehouse.ts`)

- `useInventoryKpis()` — 4-tile data
- `useInventoryGrid(filters)` — product table
- `usePendingInvoices()` — horizontal strip
- `useInvoice(id)` — detail view with live polling during SCANNING state
- `useCreateInvoice()` — mutation
- `useStartScan(invoiceId)` / `usePauseScan` / `useResumeScan` / `useCloseScan`
- `useSubmitScan()` — the high-frequency one; called on every camera detection
- `useResolveBarcode(barcode)` — returns product or "unknown" for scan feedback
- `useDiscrepancyReport(invoiceId)` — post-close reconciliation view
- `useActivityFeed()` — recent scans, refreshes every 30s
- `usePendingReviews()` — Owner-only, list of unexpected scans
- `useApproveScan()` / `useRejectScan()` — Owner actions

### 9.3 Contract-first: TS types mirror Pydantic schemas 1:1.

---

## 10. Security & privacy

- **Tenant isolation** on every query. Composite indexes `(tenant_id, X)` everywhere.
- **Role gating:** endpoint matrix in §8 enforced via `require_role()` dependencies
- **Scan snapshot audit:** `scanned_by_role` captured at scan time — never updated even if user's role later changes. Ensures history is truthful.
- **Barcode raw values:** stored for debugging but never exposed in public responses beyond the scan detail view
- **Supplier data:** treated as tenant-internal. Never surfaced to bartenders or managers.

---

## 11. Performance targets

- Scan submission → UI confirmation: **<500ms p95** (camera detection is instant; backend write is ~100-200ms)
- Activity feed: <200ms for last 20 events
- Inventory grid: <300ms for 100-product tenant
- Discrepancy report: <500ms (simple aggregation over scan rows)
- Dashboard KPI tiles: <300ms total for all 4

---

## 12. Future scope (not v1.0)

Tracked here so nothing important gets forgotten:

- **Supplier first-class entity** (§4.X deferred decision)
- **OCR on paper invoices** — scan supplier's invoice, auto-populate line items
- **Three-source reconciliation** — warehouse ↔ POS ↔ event config (blocked on Slesh credentials)
- **Bluetooth scanner integration** — when Omar approves budget; plugs into same scan pipeline
- **Restock request flow** — bar manager sends request via Chat → warehouse runner fulfills
- **Audit PDF export** — discrepancy reports as PDF for supplier disputes
- **Supplier analytics dashboard** — which suppliers are most reliable over time
- **Multi-location warehouses** — tenant with multiple physical warehouses (v2.0)
- **Expiration date tracking** — FIFO rotation, near-expiry alerts
- **Case + location barcodes** — full 3-level barcode resolution per original Backend Bible §10

---

## 13. Implementation roadmap

Mapped to the 2026-04-23 planning session.

### Session 0 — Spec (this session)
- Write this document, lock decisions, commit + push
- ~45 min

### Session 1 — Backend foundation (~4 hours)
- **Phase 1.1** Alembic migration — 5 tables, 4 enums (~20 min)
- **Phase 1.2** Pydantic schemas (~30 min)
- **Phase 1.3** SQLAlchemy models + repositories (~45 min)
- **Phase 1.4** Services — `InvoiceService`, `ScanService`, `ReconciliationEngine` (~90 min)
- **Phase 1.5** REST endpoints — all routes from §8 (~45 min)
- **Phase 1.6** End-to-end curl test + commit (~20 min)

### Session 2 — Frontend dashboard (~3 hours)
- **Phase 2.1** Hooks + TS types (~30 min)
- **Phase 2.2** 4 KPI tiles component (~45 min)
- **Phase 2.3** Product inventory grid (~45 min)
- **Phase 2.4** Invoice list + discrepancy banner (~45 min)
- **Phase 2.5** Activity feed component (~30 min)
- **Phase 2.6** Browser test + commit (~15 min)

### Session 3 — Scanner + invoice flow (~4 hours)
- **Phase 3.1** Install html5-qrcode + Scanner component (~45 min)
- **Phase 3.2** Manual-entry fallback form (~30 min)
- **Phase 3.3** Role-aware button matrix (~30 min)
- **Phase 3.4** Invoice create form (~45 min)
- **Phase 3.5** Scan session screen — live progress bars (~45 min)
- **Phase 3.6** Discrepancy report screen (~30 min)
- **Phase 3.7** Pending review queue (~20 min)
- **Phase 3.8** Browser test with real camera + commit (~15 min)

**Total: ~12 hours across 3 sessions, plus Omar review windows between each.**

---

## 14. Open questions (to resolve during implementation)

- Exact `low_stock_threshold` default — flat 10, or product-specific (e.g. 20% of historical usage)?
- Whether the `miscellaneous_description` freetext row should be searchable in the product grid, or kept invoice-internal
- UI for "convert misc row into a catalog product" — useful but deferrable
- Sound/vibration feedback tuning on successful scan (accessibility considerations)
- Whether PAUSED invoices should show on the main dashboard's "Pending Deliveries" strip, or live in a separate "Sessions" section

Polish decisions, deferrable to implementation phase.

---

## Document history

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-04-23 | Hesam | Initial spec. Supersedes Backend Bible §10. Captures Omar's invoice-reconciliation requirement as the hero feature. Supplier modeling intentionally deferred pending invoice sample review. |
