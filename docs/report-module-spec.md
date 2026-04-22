# Report Module — Specification v1.0

**Status:** Draft · **Owner:** Hesam · **Last updated:** 2026-04-22 · **Target:** Sundance June 2026

This document is the single source of truth for the XProject post-event Report module. It supersedes Section 13 of the Backend Architecture Bible and Section 3.5 of the Frontend Bible — both written before we knew what Omar actually wanted and before we knew which data would be available by Sundance.

**When this spec and any older document disagree, this spec wins.**

---

## 1. Why this module exists

Omar asked for one thing, and he asked for it clearly:

> *"I'd like there to be a written part in normal language, as if an expert consultant were talking to me the day after the event. This is the first building block of the decision intelligence we want to build together."*

Three concepts in that sentence define the entire module:

1. **"Written part in normal language"** — prose, not dashboards. The report is read linearly, top to bottom, like a letter from a trusted advisor.
2. **"As if an expert consultant were talking to me"** — first-person, opinionated, advisory tone. Not a neutral data dump. Recommendations, not just facts.
3. **"The day after the event"** — the report exists for post-event decision-making, not live operations. Timing is "tomorrow morning, on his phone, with a coffee." Not "five minutes after the last drink is poured."

Everything else — charts, tables, sections — exists only to support the prose. If a visualization does not earn its place by making the narrative more credible, it does not belong in v1.0.

---

## 2. What we are NOT building in v1.0

Previous specs listed 8 data sections plus 3 narrative sections. We are not building all of them. Five depend on features that will not exist by Sundance:

| Old section | Status in v1.0 | Why dropped |
|---|---|---|
| Warehouse Reconciliation | ❌ dropped | Warehouse module not built; Sundance will not have barcode scanners. |
| ML Accuracy | ❌ dropped | No ML models shipped. Would require faking data. |
| Event Comparison | ❌ dropped | Requires ≥2 similar past events. Fresh install has zero. |
| Product Performance | ❌ folded into Revenue section | Adds noise standalone; already implicit in revenue breakdown. |
| Consumption Ratio (standalone) | ❌ relabeled | Replaced by "Stock Reality Check" using plain language Omar uses. |

Dropped sections will be reintroduced later once their data dependencies exist. The spec is forward-compatible — adding them later is an append, not a rewrite.

We are also **not shipping the "AI-generated narrative" framing** that the current frontend mockup implies. The narrative engine is rule-based template filling, not LLM-generated prose. The UI and endpoint responses refer to it as simply **"narrative"** or **"expert summary"** — never "AI-generated." Calling rule-based output "AI" is a trust violation we will not ship.

---

## 3. Report structure — what Omar sees

Four content pages plus cover. Read-time target: **3 minutes on a phone.**

### 3.0 Cover page

- **Event name**, large, serif display face
- **Event date range**, venue name underneath
- **Total revenue**, giant number — the first thing he looks for
- **Three micro-KPIs** on one row: bars count · guests served · event duration
- XProject logomark bottom-left
- *"Preparato per Omar Bouznad · Noma Group"* / *"Prepared for Omar Bouznad · Noma Group"*
- Generation timestamp + report version (e.g. `v1 · 23 aprile 2026 · 08:15`)

### 3.1 Section 1 — Executive Narrative (the consultant's letter)

**One full page. This is the heart of the report.**

Three sub-headings, each 1–3 paragraphs of prose:

1. **Cosa è successo / What Happened** — Revenue total, per-bar leader, peak hour, one notable pattern (e.g. *"Bar 3 carried the night"*, *"cocktail sales outpaced beer 2:1"*). Template-driven with data injection.
2. **Cosa ha funzionato / What Worked** — Operational highlights: burn rates steady, no stock-outs at peak, alerts acknowledged quickly. For v1.0 this leans on consumption-efficiency and alert-response time, not ML accuracy (doesn't exist yet).
3. **Cosa fare al prossimo / What To Do Next** — Three to four concrete, actionable recommendations. Each bullet tied to a specific data point. Example: *"Aumenta lo stock di vodka del 15% — il Bar 3 è rimasto senza alle 23:40 durante il picco."*

Tone: warm, direct, opinionated. Uses Omar's first name. Avoids hedging. Written as if the consultant knows the operation.

### 3.2 Section 2 — Revenue Breakdown

**One page.** Three elements stacked:

- **Horizontal bar chart** — revenue per bar, sorted descending, top bar highlighted
- **Revenue-over-time line chart** — cumulative revenue, peak-hour band shaded
- **KPI strip** — revenue/hour, revenue/bar average, top product (name + units)

No tables here. Visuals only. The narrative already told the story; this is the evidence.

### 3.3 Section 3 — Stock Reality Check

**One page.** One table per bar, stacked vertically (paginated if >3 bars). Columns:

| Product | Opening | Closing | Consumed | Burn rate (/h) | Stock-out? |

Row coloring: stock-out = red tint; within 10% of plan = green; in-between = neutral.

Replaces "Consumption Ratio" — same math, operational language.

### 3.4 Section 4 — Alerts Timeline

**One page.** Chronological list per alert:

- Severity pill (WARNING amber, CRITICAL red, ANOMALY purple owner-only badge)
- Timestamp (HH:MM)
- Bar name
- Alert title
- Acknowledged-by + ack time (or *"unacknowledged"*)

Demonstrates the "delayed detection" problem being solved in real time — the core product thesis, proven.

### 3.5 Appendix (placeholder only, v1.1+)

Raw metrics per bar × product. **Not shipped in v1.0.** Placeholder so we remember to add it when Omar asks.

---

## 4. Data model

### 4.1 `reports` table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK | Multi-tenant scoping. |
| `event_id` | UUID FK | |
| `version` | int | Starts at 1, increments on regenerate. |
| `superseded_by` | UUID FK nullable | Points to newer version. |
| `status` | enum | `pending`, `generating`, `ready`, `failed`. |
| `language` | enum | `it`, `en`. Two rows per (event, version). |
| `data_json` | jsonb | Full `ReportData` snapshot. |
| `pdf_bytes` | bytea nullable | Generated PDF. ~200KB. NULL until Phase 2 ships. |
| `generated_at` | timestamptz nullable | When status → `ready`. |
| `generated_by` | UUID FK nullable | User ID if on-demand; NULL if auto-triggered. |
| `failure_reason` | text nullable | Only if `status = failed`. |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Indexes:**
- UNIQUE `(tenant_id, event_id, version, language)`
- `(tenant_id, event_id, status)` for list lookups
- `(tenant_id, status, generated_at DESC)` for admin dashboards

### 4.2 `ReportData` Pydantic schema (snake_case throughout)

```python
class ReportEventInfo(BaseModel):
    event_id: UUID
    event_name: str
    venue_name: str
    started_at: datetime
    ended_at: datetime
    duration_hours: float
    bars_count: int
    guests_served: int | None   # NULL until ticketing integration
    expected_guests: int | None

class ReportRevenueKpis(BaseModel):
    total_revenue: Decimal
    revenue_per_hour: Decimal
    revenue_per_bar_avg: Decimal
    top_product_name: str | None
    top_product_units: int | None
    peak_hour_start: datetime | None
    peak_hour_revenue: Decimal | None

class ReportBarRevenue(BaseModel):
    bar_id: UUID
    bar_name: str
    revenue: Decimal
    revenue_pct: float
    transactions_count: int
    rank: int   # 1 = highest

class ReportStockRow(BaseModel):
    bar_id: UUID
    bar_name: str
    product_id: UUID
    product_name: str
    opening_qty: Decimal
    closing_qty: Decimal
    consumed_qty: Decimal
    burn_rate_per_hour: Decimal
    stock_out_occurred: bool
    stock_out_time: datetime | None
    consumption_vs_plan_pct: float | None

class ReportAlertRow(BaseModel):
    alert_id: UUID
    alert_type: Literal["depletion", "anomaly"]
    severity: Literal["warning", "critical", "info"]
    bar_id: UUID | None
    bar_name: str | None
    title: str
    message: str
    fired_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_name: str | None
    audience: Literal["all", "owner_only", "manager_only"]

class ReportNarrative(BaseModel):
    what_happened: str
    what_worked: str
    what_next: list[str]   # 3–4 bullets

class ReportData(BaseModel):
    report_id: UUID
    version: int
    language: Literal["it", "en"]
    generated_at: datetime
    event: ReportEventInfo
    revenue_kpis: ReportRevenueKpis
    bar_revenues: list[ReportBarRevenue]
    stock_rows: list[ReportStockRow]
    alerts: list[ReportAlertRow]
    narrative: ReportNarrative
```

### 4.3 API response envelopes

```python
class ReportSummary(BaseModel):
    """List view — lightweight."""
    id: UUID
    event_id: UUID
    event_name: str
    event_started_at: datetime
    event_ended_at: datetime
    version: int
    status: ReportStatus
    language: ReportLanguage
    generated_at: datetime | None
    total_revenue: Decimal | None   # denormalized for list card
    alerts_count: int | None
    top_bar_name: str | None

class ReportResponse(BaseModel):
    """Detail view."""
    id: UUID
    event_id: UUID
    version: int
    superseded_by: UUID | None
    status: ReportStatus
    language: ReportLanguage
    generated_at: datetime | None
    data: ReportData | None   # NULL while pending/generating

class PortfolioKpis(BaseModel):
    """For the Portfolio Insights Strip."""
    total_events_completed: int
    lifetime_revenue: Decimal
    avg_event_revenue: Decimal
    best_event_name: str | None
    best_event_revenue: Decimal | None
    events_delta_vs_last_quarter: int
    revenue_delta_pct_yoy: float | None
    avg_revenue_delta_vs_last_quarter: Decimal | None
```

---

## 5. Generation lifecycle

### 5.1 State machine

```
  [pending] ──► [generating] ──► [ready]
                     │
                     └─error──► [failed] ──(manual regenerate)──► new row v2
```

### 5.2 Auto-trigger

Arq cron `check_events_for_report_generation` runs every 5 minutes:

```python
cutoff = utcnow() - timedelta(minutes=15)
stmt = select(Event).where(
    Event.ended_at < cutoff,
    Event.status == EventStatus.COMPLETED,
    ~exists().where(Report.event_id == Event.id),
)
```

For each match: enqueue `generate_report_job(event_id, "it")` AND `generate_report_job(event_id, "en")`. Two jobs per event.

### 5.3 On-demand

`POST /reports/generate` body `{event_id, language}`. Creates row with `status=pending`, enqueues job, returns row. Idempotent — if latest version for `(event_id, language)` already in `ready`, returns it.

### 5.4 Regeneration

`POST /reports/{id}/regenerate` — Owner-only. Creates new row with `version = previous + 1`, sets `previous.superseded_by = new.id`. **Old row never deleted.** Audit trail forever.

### 5.5 Failure handling

- `status` → `failed`, `failure_reason` captured
- No auto-retry (row exists, so cron won't re-pick event)
- Owner sees error badge on list card
- Manual retry via `POST /reports/{id}/regenerate`

---

## 6. Narrative engine

### 6.1 Design

Paired IT+EN template dictionary. Each template:
- `key` — debug identifier (`revenue_leader`, `peak_hour`, etc.)
- `condition` — lambda over `ReportData` deciding if sentence fires
- `priority` — ordering within section (lower = earlier)
- `it`, `en` — template strings with `{field}` placeholders

Example:

```python
TEMPLATES_WHAT_HAPPENED = [
    {
        "key": "revenue_leader",
        "condition": lambda d: d.bar_revenues and d.bar_revenues[0].revenue_pct >= 30,
        "priority": 10,
        "it": "{bar_name} ha guidato la serata con il {pct}% del fatturato totale.",
        "en": "{bar_name} led the night, generating {pct}% of total revenue.",
    },
    {
        "key": "peak_hour",
        "condition": lambda d: d.revenue_kpis.peak_hour_start is not None,
        "priority": 20,
        "it": "Il picco è arrivato alle {hour}, con €{peak_rev:,.0f} in un'ora.",
        "en": "Peak consumption hit at {hour}, generating €{peak_rev:,.0f} in one hour.",
    },
]
```

### 6.2 Rendering

For each section:
1. Filter templates whose `condition(data)` returns `True`
2. Sort by `priority`
3. Format `it` or `en` string per `language` param with `ReportData` fields
4. Join with spaces for prose, keep as list for `what_next`

### 6.3 File organization

```
app/modules/reports/narrative/
├── __init__.py
├── engine.py              # filter/sort/render
├── templates_happened.py
├── templates_worked.py
└── templates_next.py
```

Each template file is pure data. No imports beyond `ReportData`. Fully testable.

---

## 7. Endpoints

Base: `/api/v1`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/events/{event_id}/reports` | Owner | List all report versions for an event. |
| POST | `/reports/generate` | Owner | On-demand. Body: `{event_id, language}`. |
| GET | `/reports/{id}` | Owner | Full `ReportResponse`. Respects `?lang=it\|en`. |
| GET | `/reports/{id}/pdf` | Owner | `application/pdf` response. |
| POST | `/reports/{id}/regenerate` | Owner | Creates v2+. Body: `{language?}`. |
| GET | `/reports` | Owner | Index. Filters: `status`, `event_id`, `language`, `limit`, `cursor`. |
| GET | `/reports/portfolio/kpis` | Owner | `PortfolioKpis` for index-page strip. |

**Manager access: none.** Reports are Owner-only in v1.0. Manager-facing recap is a future module.

---

## 8. Frontend contract

### 8.1 Reports index page (`/reports`)

Replaces current mockup. Top-to-bottom:

1. **Page header** — title, subtitle, `[+ Generate New Report]` button (opens modal to pick event + language)
2. **Portfolio Insights Strip** — 4 tiles from `GET /reports/portfolio/kpis`
3. **Past Reports list** — enriched cards, one per event's latest version per language

**REMOVED from current mockup:**
- ❌ Blue *"Current Event / In Progress"* block — category error; Dashboard is the live surface
- ❌ *"AI-Generated Narrative"* index-page accordion — belongs inside a specific report, not on the list

### 8.2 Report detail page (`/reports/:id`)

New route. Renders `ReportResponse` inline with same 4-section structure as the PDF:
- Cover block
- Narrative section (prose from `ReportData.narrative`)
- Revenue section (Recharts)
- Stock section (tables)
- Alerts section (list)

Top toolbar: `[📄 Download PDF]` · `[🔄 Regenerate]` (Owner only) · language toggle IT ↔ EN.

### 8.3 mockData.ts contract

`types.ts` and `mockData.ts` mirror Pydantic schemas 1:1. Mock → real swap is one line per hook.

---

## 9. Error handling & edge cases

| Case | Behavior |
|---|---|
| Zero transactions | Report generates. Revenue: *"Nessuna transazione registrata."* |
| Zero alerts | Timeline empty-state: *"Nessun alert — la serata è filata liscia."* (good message, not error) |
| Zero bars configured | Generation aborts; `failure_reason='no_bars_configured'`. Friendly UI error. |
| Narrative produces zero sentences | Fallback: *"Evento concluso. I dati completi sono nelle sezioni seguenti."* |
| PDF fails (ReportLab crash) | Status `failed`, JSON snapshot still stored → UI still renders inline. |
| Tenant deleted mid-generation | Job no-ops, marks `failed` with `tenant_removed`. |

---

## 10. Security & privacy

- **Tenant isolation:** every query filters by `tenant_id`. Composite index `(tenant_id, event_id)` prevents accidental cross-tenant leakage.
- **Role gating:** all endpoints require `role='owner'`. Managers → HTTP 403.
- **Audit:** `generated_by` captures user for on-demand. `created_at`/`updated_at` never mutated post-write once `ready`.
- **PII:** customer names never appear. Staff names only in `acknowledged_by_name` on alerts — internal operational data.
- **PDF access:** NOT public. Every `/reports/{id}/pdf` re-validates auth.

---

## 11. Performance targets

- Auto-trigger latency: `ready` within 2 min of `ended_at + 15min`
- On-demand latency: `ready` within 30s of `POST /reports/generate`
- List endpoint p95: <200ms for 100 events
- PDF download: <500ms (served from `pdf_bytes`, no regeneration on read)
- DB row size: ~250KB average (50KB JSON + 200KB PDF). 100 events ≈ 25MB. Trivial.

---

## 12. Future scope (not v1.0)

- **v1.1:** Appendix with raw metrics per bar × product
- **v1.2:** Event Comparison (once ≥2 similar events)
- **v1.3:** Manager-facing recap (own-bar data, no anomalies)
- **v2.0:** LLM-generated narrative variant (Pro tier; template engine stays as fallback)
- **v2.1:** ML Accuracy section (once Model A ships)
- **v2.2:** Warehouse Reconciliation (once barcode scanning ships)
- **v2.3:** Event P&L (once cost entry in Event Create ships)
- **v3.0:** Scheduled email delivery

---

## 13. Implementation roadmap

| Phase | Step | Deliverable | Estimate |
|---|---|---|---|
| 0 | Spec | This file | 30 min |
| 1.1 | Alembic migration | `reports` table in dev DB | 15 min |
| 1.2 | Pydantic schemas | `ReportData` + envelopes | 20 min |
| 1.3 | SQLAlchemy model + repository | `Report` ORM + helpers | 15 min |
| 1.4 | ReportAggregator service | Pure aggregation | 45 min |
| 1.5 | NarrativeEngine service | Template render | 45 min |
| 1.6 | ReportService | Orchestration + persist | 20 min |
| 1.7 | REST endpoints | 7 endpoints from §7 | 30 min |
| 1.8 | Manual integration test | Curl flow | 15 min |
| 2.1 | Chart generation | Matplotlib Agg → PNG | 30 min |
| 2.2 | Cover + narrative layout | ReportLab | 30 min |
| 2.3 | Data sections layout | ReportLab | 45 min |
| 2.4 | IT/EN polish | Fonts + spacing | 15 min |
| 3.1 | mockData.ts | Mirror Pydantic | 15 min |
| 3.2 | TanStack Query hooks | 5 hooks | 30 min |
| 3.3 | Strip dead sections | Delete blue card + narrative accordion | 15 min |
| 3.4 | PortfolioKpisStrip | 4-tile component | 45 min |
| 3.5 | Enriched ReportCard | Thumbnail + KPIs + badges | 45 min |
| 3.6 | ReportDetailPage | Full inline render | 45 min |
| 3.7 | Browser test + commit | End-to-end | 15 min |
| 4.1 | Arq cron | Auto-generation job | 30 min |
| 4.2 | Integration test | Simulated event-end | 15 min |
| 4.3 | Docs + commit | Close out | 15 min |

**Total: ~9 hours across 3 sessions.**

---

## 14. Open questions (resolve during implementation)

- Cover-page display font — default serif vs Playfair/Lora
- Chart palette — Tailwind tokens vs print-optimized palette
- Portfolio "YoY" metric — calendar-year vs trailing-12-months
- Minimum event size for portfolio inclusion (avoid smoke-test skew)

Polish decisions, deferrable to Phase 2 or 3.

---

## Document history

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-04-22 | Hesam | Initial spec. Supersedes Backend Bible §13 + Frontend Bible §3.5. |
