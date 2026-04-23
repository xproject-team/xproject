# Predictions Module — Specification v1.0

**Status:** Draft · **Owner:** Hesam · **Last updated:** 2026-04-23 · **Target:** Sundance June 2026

This document is the single source of truth for the XProject Predictions module. It supersedes Section 11 of the Backend Architecture Bible and Section 3.4 of the Frontend Bible where they disagree.

**When this spec and any older document disagree, this spec wins.**

---

## 1. Why this module exists

Omar plans events without knowing what will happen. He sets bar counts, stock levels, and staffing based on intuition and last year's numbers — which live in multiple spreadsheets he cannot cross-reference quickly. The cost of being wrong is visible on event night: bars running dry, staff idle, revenue left on the table.

The Predictions module answers one question: *"Given the events we've run before, what should Omar expect from this one?"*

Three design pillars drive every decision:

1. **Honest over impressive.** If we can't predict it well, we don't predict it. Empty states are always better than made-up numbers.
2. **Progressively useful.** Day 1 the module is scaffolding with calm empty states. As events complete, the predictions sharpen. No retraining, no rebuilds — the same function produces better output with more data.
3. **Replaceable prediction engine.** Today a `HeuristicPredictor` uses historical averages with scaling. Later (Track 2) an `MLPredictor` uses scikit-learn. Both implement the same interface; the API, frontend, and storage do not change.

---

## 2. What we are NOT building in v1.0

Dropped sections vs the Backend Bible §11 + §11.1:

| Old scope | Status in v1.0 | Why dropped |
|---|---|---|
| scikit-learn GradientBoostingRegressor (Model A) | ❌ deferred to Track 2 | Needs 15–25 historical events. We have 0. Training on nothing produces nothing. |
| RandomForestClassifier for risk flags | ❌ deferred to Track 2 | Same reason. Plus classifier needs labeled "risk occurred" events. |
| Model B — Exponential smoothing during live events | ❌ deferred to v1.1 | Recalibration path requires Model A baseline to recalibrate against. Out of scope until Track 2. |
| Model C — Accuracy tracking + Owner override feedback loop | ⚠️ partial | We record predicted vs actual (post-event), but do not yet feed back into a trained model. Full loop ships with Track 2. |
| Model E — Ticketing intelligence (SARIMA on velocity) | ❌ deferred | Requires ticket-sales data ingestion pipeline (TK-1). Separate module. |
| Synthetic bootstrap training data | ❌ rejected by design | Fabricated numbers displayed as predictions is a trust violation — same class of issue as the "AI-generated narrative" we deleted from Reports. |

We also explicitly reject any UI that labels the output as "AI" or "ML-powered" until the ML model is actually shipped (Track 2). The current engine is honest heuristic math, and the UI names it accordingly: *"Prediction based on N past events."*

---

## 3. What the page shows (spec §8.1)

**Route:** `/predictions`

**Access:** Owner only. Managers and bartenders redirect.

**Two states:**

### 3.1 Zero-history state (today)

Clean empty state centered on page:
- Icon 📊
- Heading: *"Predictions will appear after your first completed event."*
- Body: *"The system learns from every event you run — revenue patterns, peak hours, stock consumption. After one completed event you'll see early predictions with wide confidence ranges. After five, they sharpen significantly."*
- Secondary CTA: *"View past reports →"* linking to `/reports`

No fake data. No demo prediction cards. No "try it with sample data" toggles.

### 3.2 Has-history state (after first event completes)

Same layout per your current screenshot, but every number sourced from `HeuristicPredictor` output against real data:

1. **Header**
   - Title: *"Demand Predictions"*
   - Subtitle: *"Based on N past events · Generated {timestamp}"* — clearly says how many events the prediction comes from
   - Right-side button: *"Regenerate Predictions"* → triggers on-demand run

2. **5 prediction cards** (horizontal row, grid-cols-5 on desktop, wraps on mobile):
   - **Total Revenue** — projected euros for this event, with trend arrow vs last event
   - **Per-Category Demand** — one card each for beer / spirits / wine / mixers / cocktails (or collapse to one card with tabs if space-constrained)
   - **Peak Hour Window** — single card: *"21:30–22:30 · highest demand window"*
   - **Staff Recommendation** — *"N bartenders recommended across M bars"*
   - **Stock-Out Risks** — *"K products at risk of depletion"*

3. **Revenue Forecast Chart** — line chart showing projected cumulative revenue over event duration, with confidence band (±σ). X-axis is hours since start, Y-axis is euros.

4. **Per-Category Detail Table** — for each of 5 categories: predicted units, confidence %, historical average, recommended allocation per bar. Sortable.

5. **Accuracy Widget** (only shown if ≥2 past events): *"Last prediction accuracy: Revenue 87%, Demand 92%."* Small, calm, not a hero element. Uses `Model C` post-event tracker data.

### 3.3 Confidence ranges

Every prediction is a range, not a point. Display format: *"140 units (range 110-170, 80% confidence)"*. Until ≥5 events exist, confidence is labeled `low`. At 5-15 events it's `medium`. ≥15 events `high`.

---

## 4. Data model

### 4.1 `predictions` table

Mirrors the pattern of `reports` — one row per generation. Version + supersede semantics.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK → tenants.id CASCADE | |
| `event_id` | UUID FK → events.id CASCADE | |
| `version` | int, default 1 | Increments on regenerate |
| `superseded_by` | UUID FK → predictions.id SET NULL | |
| `status` | enum | `pending`, `generating`, `ready`, `failed`, `insufficient_data` |
| `predictor_type` | enum | `heuristic` (today), `ml` (Track 2) |
| `data_json` | jsonb | Full `PredictionData` snapshot (see §4.2) |
| `based_on_event_count` | int | How many historical events informed this prediction |
| `confidence_tier` | enum | `low`, `medium`, `high` |
| `generated_at` | timestamptz nullable | |
| `generated_by` | UUID FK → users.id SET NULL | |
| `failure_reason` | text nullable | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

**Indexes:**
- UNIQUE `(tenant_id, event_id, version)` — one prediction per version per event
- `(tenant_id, event_id, status)` — fast lookup for latest-ready prediction
- `(tenant_id, status, generated_at DESC)` — admin dashboards

**Constraint:** `superseded_by` must reference a row with higher `version`.

### 4.2 `PredictionData` Pydantic schema

```python
class PredictionRange(BaseModel):
    """Every prediction is a range, not a point."""
    low: Decimal
    mid: Decimal
    high: Decimal
    confidence_pct: float  # 0-100

class PredictionRevenue(BaseModel):
    total: PredictionRange
    per_bar: list["PredictionBarRevenue"]
    vs_last_event_pct: float | None  # None if first event

class PredictionCategoryDemand(BaseModel):
    category: Literal["beer", "spirits", "wine", "mixers", "cocktails"]
    units: PredictionRange
    trend: Literal["up", "stable", "down"]

class PredictionPeakHour(BaseModel):
    window_start: datetime
    window_end: datetime  # typically +1h
    predicted_revenue_share_pct: float  # e.g. 34.0 = 34% of event revenue in peak hour

class PredictionStaff(BaseModel):
    total_bartenders: PredictionRange
    per_bar: list["PredictionBarStaff"]

class PredictionRiskFlag(BaseModel):
    product_id: UUID
    product_name: str
    bar_id: UUID
    bar_name: str
    stockout_probability: float  # 0.0-1.0
    predicted_stockout_time: datetime | None

class PredictionData(BaseModel):
    prediction_id: UUID
    version: int
    generated_at: datetime
    based_on_event_count: int
    confidence_tier: Literal["low", "medium", "high"]
    event: ReportEventInfo  # reuse from reports module
    revenue: PredictionRevenue
    category_demand: list[PredictionCategoryDemand]
    peak_hour: PredictionPeakHour | None
    staff: PredictionStaff
    risk_flags: list[PredictionRiskFlag]
```

### 4.3 API response envelopes

```python
class PredictionSummary(BaseModel):
    """List view."""
    id: UUID
    event_id: UUID
    event_name: str
    version: int
    status: PredictionStatus
    predictor_type: PredictorType
    confidence_tier: ConfidenceTier
    based_on_event_count: int
    generated_at: datetime | None

class PredictionResponse(BaseModel):
    """Detail view."""
    id: UUID
    event_id: UUID
    version: int
    superseded_by: UUID | None
    status: PredictionStatus
    predictor_type: PredictorType
    confidence_tier: ConfidenceTier
    based_on_event_count: int
    generated_at: datetime | None
    data: PredictionData | None  # NULL while pending/generating, or if status=insufficient_data
    insufficient_data_message: str | None  # human-readable when status=insufficient_data
```

---

## 5. The `BasePredictor` interface

The core architectural contract. Lives in `app/modules/predictions/predictors/base.py`.

```python
class BasePredictor(ABC):
    """Every prediction engine must implement this interface.

    Today: HeuristicPredictor (historical averages + scaling)
    Track 2: MLPredictor (scikit-learn GradientBoostingRegressor)
    The API, frontend, and storage do not change between the two.
    """

    @abstractmethod
    async def predict(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> PredictionData | PredictionInsufficientData:
        """Produce a prediction for the given event.

        Returns PredictionInsufficientData (not an exception) when historical
        data is below the minimum threshold for this predictor type.
        Service layer converts this to status='insufficient_data' on the row.
        """
        ...

    @property
    @abstractmethod
    def predictor_type(self) -> Literal["heuristic", "ml"]: ...

    @abstractmethod
    def minimum_events_required(self) -> int: ...
```

### 5.1 `HeuristicPredictor` (today)

- `predictor_type = "heuristic"`
- `minimum_events_required = 1`
- Algorithm summary:
  - **Total revenue:** `avg(past_event.total_revenue / past_event.guest_count) × this_event.expected_guest_count`
  - **Per-category demand:** same per-guest scaling, segmented by category
  - **Peak hour:** mode of past events' peak hours (fallback: 21:30-22:30 if no history shows clear peak)
  - **Staff recommendation:** `past_event.bars_count` average, scaled by guest ratio
  - **Risk flags:** for each (bar, product) in this event's config, compute expected consumption = historical `consumed_qty / guest_count × this_event.expected_guest_count`. If expected > 90% of allocated, flag.
  - **Confidence ranges:** ±σ of the historical sample (widens with fewer events)
  - **Confidence tier:** `low` if 1-4 events, `medium` if 5-14, `high` if ≥15

### 5.2 `MLPredictor` (Track 2, not this session)

- `predictor_type = "ml"`
- `minimum_events_required = 15`
- Algorithm: GradientBoostingRegressor + RandomForestClassifier per Backend Bible §11
- Placeholder class exists in the codebase with `NotImplementedError` — makes the interface obvious to Track 2.

### 5.3 Selection logic

`PredictionService` chooses the predictor:
- If `MLPredictor.is_ready(tenant)` returns True → use it
- Otherwise → fall back to `HeuristicPredictor`
- `is_ready()` checks: minimum events required AND trained model file present on disk

Track 2 flips `MLPredictor.is_ready` from `return False` to actual logic. No other code changes.

---

## 6. Generation lifecycle

### 6.1 State machine

```
[pending] → [generating] → [ready]
                │
                ├─ insufficient_data → [insufficient_data]  (terminal, can re-run)
                │
                └─ error → [failed]  (terminal, admin regen creates v+1)
```

### 6.2 On-demand trigger

`POST /predictions/generate` with body `{event_id}`. Creates a row with `status=pending`, enqueues arq job `generate_prediction(event_id)`. Idempotent: if latest prediction is `ready` AND event config hasn't changed since, returns existing row.

### 6.3 Auto-regen on config change (Q2 decision)

Triggered by specific event mutations — NOT on every PATCH:

| Mutation | Auto-regen? |
|---|---|
| Bars added/removed from event | ✅ yes |
| `expected_guest_count` changed | ✅ yes |
| Bar menu/stock changed | ✅ yes |
| Event name/date changed | ❌ no (cosmetic) |
| Status transition (draft → live) | ❌ no (prediction already generated) |

Hook: `EventService.update_event()` checks which fields changed; if any auto-regen trigger fields are in the diff, enqueues `generate_prediction` as fire-and-forget side effect.

### 6.4 Regeneration (manual)

`POST /predictions/{id}/regenerate` → creates v+1 identical to the reports-module pattern. Old row sets `superseded_by = new.id`. Never deleted.

### 6.5 Failure handling

- Aggregator failure → row marked `failed`, reason stored, service raises `PredictionGenerationError`
- Insufficient data → row marked `insufficient_data`, `insufficient_data_message` populated, NOT an error. UI shows the empty-state banner.

---

## 7. Endpoints

Base: `/api/v1/predictions`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/events/{event_id}` | Owner | Latest prediction for an event (or 404 if none) |
| GET | `/events/{event_id}/history` | Owner | All versions including superseded |
| POST | `/generate` | Owner | On-demand. Body: `{event_id}` |
| GET | `/{prediction_id}` | Owner | Full `PredictionResponse` |
| POST | `/{prediction_id}/regenerate` | Owner | Creates v+1 |

**Manager access:** none in v1.0. Per-bar prediction views (managers see only their bar) ship in v1.2 per spec §1.3 roadmap.

---

## 8. Frontend contract

### 8.1 Reports-module mirror

Same file structure as `features/reports/useReports.ts`:

```
features/predictions/usePredictions.ts     // hooks + types
pages/predictions/PredictionPage.tsx       // index + detail combined
```

Types mirror backend Pydantic schemas 1:1. Query keys:

```ts
export const predictionsKeys = {
  all: ['predictions'] as const,
  forEvent: (eventId: string) =>
    [...predictionsKeys.all, 'for-event', eventId] as const,
  detail: (predictionId: string) =>
    [...predictionsKeys.all, 'detail', predictionId] as const,
}
```

### 8.2 Hooks (6 total)

- `usePredictionForEvent(eventId)` → latest ready prediction or `insufficient_data`
- `usePredictionsHistory(eventId)` → all versions
- `usePrediction(predictionId)` → detail view
- `useGeneratePrediction()` → mutation
- `useRegeneratePrediction(predictionId)` → mutation
- `useActiveEventId()` — **NEW helper** that returns the currently-live or most-recent-draft event ID from Zustand (existing), so the Predictions page knows which event to show. Without an active event, page shows a "select an event first" message.

### 8.3 Page states

Three states the page must handle cleanly:

| State | Trigger | UI |
|---|---|---|
| **No active event** | Zustand has no `activeEventId` | Neutral empty state, *"Select an event from the Events page to view predictions."* |
| **Insufficient data** | API returns `status=insufficient_data` | The calm 📊 empty state from §3.1 |
| **Ready** | API returns `status=ready` with `data` | Full 5-card + chart + table layout from §3.2 |

---

## 9. Error handling & edge cases

| Case | Behavior |
|---|---|
| First-ever event | Heuristic returns insufficient_data. Status rendered with the calm empty state. |
| Event has no bars configured yet | `PredictionGenerationError`, status=failed, reason='no_bars_configured'. Frontend shows red banner: "Complete event configuration before generating predictions." |
| Tenant deleted mid-generation | Job no-ops; row marked failed with reason `tenant_removed`. |
| `expected_guest_count` is NULL | HeuristicPredictor cannot scale. Returns insufficient_data with message: "Set expected guest count in event details to generate predictions." |
| Historical events exist but all have 0 transactions | Heuristic filters out zero-revenue events from its sample. If that leaves <1 event, returns insufficient_data. |
| Regenerate when event already ended | Allowed. Creates new version. Useful for Track 2 Model C accuracy calibration. |

---

## 10. Security & privacy

- **Tenant isolation** on every query. `(tenant_id, event_id)` composite filter enforced at repository level.
- **Role gate:** all endpoints `require_owner`. Managers → 403.
- **PII:** no customer PII appears in predictions. Product and bar names only.
- **PDF of predictions:** NOT shipped in v1.0. Spec §12 only — Track 2 may add.

---

## 11. Performance targets

- **On-demand latency:** p95 < 2s for HeuristicPredictor on events with ≤20 past events
- **Auto-regen latency:** p95 < 5s (fire-and-forget from EventService.update_event)
- **List endpoint p95:** < 200ms
- **DB row size:** ~10KB per prediction (JSON snapshot). 100 predictions ≈ 1MB. Trivial.

---

## 12. Future scope (not v1.0)

Tracked here so nothing important gets forgotten:

- **Track 2 (dedicated session):** Analyze Slesh 2024/2025 CSVs. Train Model A (GradientBoostingRegressor). Build `MLPredictor`. Populate training data from historical events. Calibrate confidence bands.
- **v1.1:** Model B live recalibration during events (10-min cycle)
- **v1.2:** Per-bar manager predictions (filtered view)
- **v1.3:** Model C Owner-override feedback loop (human-in-the-loop ML)
- **v1.4:** Weather context integration (Google Weather API)
- **v1.5:** Ticketing intelligence — SARIMA on ticket velocity
- **v2.0:** PDF export of predictions (pre-event planning brief)
- **v2.1:** Cross-event comparison view (this event vs similar past events)

---

## 13. Implementation roadmap

Mapped to phases from 2026-04-23 session:

| Phase | Step | Deliverable | Estimate |
|---|---|---|---|
| 0 | Spec | This file | 30 min |
| 1.1 | Alembic migration | `predictions` table landed | 15 min |
| 1.2 | Pydantic schemas | Full §4.2 hierarchy | 25 min |
| 1.3 | SQLAlchemy model | ORM class with `TenantScopedModel` | 15 min |
| 1.4 | Repository | Read/write helpers | 30 min |
| 1.5 | `BasePredictor` interface + `HeuristicPredictor` | Pluggable engine, 5-prediction implementation | 90 min |
| 1.6 | `PredictionService` | Orchestrator + transaction boundary | 30 min |
| 1.7 | REST endpoints | 5 endpoints from §7 | 30 min |
| 1.8 | Arq task + auto-regen hook | Cron-free job + EventService integration | 30 min |
| 2.1 | Frontend: hooks + types | 6 hooks, 14 interfaces | 30 min |
| 2.2 | PredictionPage rewrite | 3 states, 5 cards, chart, table | 90 min |
| 2.3 | Browser test + commit | End-to-end verification | 15 min |

**Total: ~7 hours across 1-2 sessions.**

---

## 14. Open questions (resolve during implementation)

- Exact confidence-band math for low-n samples (Student's t-distribution vs simple σ?)
- Whether "peak hour" should be a 60-min window or a 30-min window
- Staff recommendation formula (flat guest/bartender ratio vs tiered)
- Whether auto-regen should debounce (e.g., if Owner edits 5 fields in 2 min, only regen once at end)

All deferrable to Phase 1.5 implementation. Design decisions, not blockers.

---

## Document history

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-04-23 | Hesam | Initial spec. Supersedes Backend Bible §11 + Frontend Bible §3.4. |
