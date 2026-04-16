# Backend Contract — XProject API

Single source of truth for backend architecture, endpoints, state machines,
invariants, database schema, and error conventions. Every new endpoint or
migration must cross-check against this document.

Last updated: 2026-04-16
Owner: Hesam
Status: v1.0

---

## 1. Architecture principles

Every module in /backend/app/modules/{name}/ MUST follow these 5 principles:

### 1.1 Layered architecture
4 files per module, one responsibility each:

  router.py      FastAPI routes. Parse request, call service, return response.
  service.py     Business logic, permission checks, state transitions.
  repository.py  DB queries only. No SQL outside this file.
  models.py      SQLAlchemy table definitions.
  schemas.py     Pydantic request/response contracts.

Rules:
- router NEVER talks to repository directly
- service NEVER writes SQL
- repository NEVER returns HTTP responses

### 1.2 Contract-first with Pydantic
Every endpoint has typed XxxCreate, XxxUpdate, XxxResponse schemas.
Frontend types.ts mirrors these field-for-field.
No endpoint returns ad-hoc JSON dicts.

### 1.3 State machines as explicit code
Status transitions defined ONCE in app/modules/events/state_machine.py.
Allowed transitions listed as data, not scattered if-statements.

### 1.4 Migrations for every schema change
Every DB change via Alembic. Never ALTER TABLE directly.

### 1.5 ACID transactions on mutations
Every POST/PATCH/DELETE wrapped in a DB transaction.
Service layer owns the transaction boundary.
If anything raises, everything rolls back.

---

## 2. Event state machine

### 2.1 States
draft, active, live, completed

### 2.2 Allowed transitions (one-way only)

  draft --activate--> active        via POST /events/{id}/activate
  active --start--> live            via POST /events/{id}/start
  live --end--> completed           via POST /events/{id}/end
  live --auto-end--> completed      cron job when now() > ended_at

Any other transition returns HTTP 409 Conflict.

### 2.3 Invariant: AT MOST ONE live event per tenant

Enforced at DB level via partial unique index:

  CREATE UNIQUE INDEX one_live_event_per_tenant
    ON events (tenant_id) WHERE status = 'live';

When POST /events/{id}/start is called:
  IF another event in same tenant has status = 'live':
    IF that event.ended_at < now():  auto-end it in same transaction, then start new
    ELSE:                            return 409 with conflicting_event payload
  ELSE:                              start the requested event

### 2.4 Transition atomicity
Every status change is ONE DB transaction. External observers (Dashboard polls)
NEVER see 0 or 2 live events. Consistency guaranteed.

### 2.5 Idempotency
All transition endpoints are idempotent:
  POST /start on an already-Live event -> 200 OK with current state
  POST /end on an already-Completed event -> 200 OK with current state
  No errors, safe to retry.

---

## 3. Edit rules per status

| Field          | Draft | Active | Live   | Completed |
|----------------|-------|--------|--------|-----------|
| name           | edit  | edit   | edit   | read-only |
| date           | edit  | edit   | LOCKED | read-only |
| location       | edit  | edit   | LOCKED | read-only |
| bars_count     | edit  | edit   | LOCKED | read-only |
| expected_guests| edit  | edit   | edit   | read-only |
| status         | (transition endpoints only, never PATCH)               |
| ended_at       | edit  | edit   | extend-only (cannot shorten below now()) | read-only |

Backend enforces via service layer guard BEFORE hitting DB.
Violations return HTTP 409 Conflict.

### 3.1 Bars on Live events
All bar mutations BLOCKED:
  POST   /events/{id}/bars     -> 409 "Cannot add bar to live event"
  PATCH  /events/{id}/bars/{b} -> 409 "Cannot edit bar on live event"
  DELETE /events/{id}/bars/{b} -> 409 "Cannot delete bar on live event"

### 3.2 Products on Live events
POST (create new product): BLOCKED with 409.
PATCH price on existing: BLOCKED with 409 "Prices locked during live event"
PATCH name/category on existing: BLOCKED with 409
DELETE: BLOCKED. Instead, PATCH is_archived = true (hides from new sales, preserves history).

### 3.3 Delete rules
| Entity     | Draft        | Active       | Live | Completed |
|------------|--------------|--------------|------|-----------|
| Event      | CASCADE all  | RESTRICT     | NO   | NO        |
| Bar        | allowed      | allowed      | NO   | NO        |
| Product    | allowed      | allowed      | archive only | NO |

When an event is deleted while in Draft: all child bars, products, recipes,
and stock allocations are deleted in the same DB transaction (CASCADE).
Once an event is Active or later, delete is blocked (use End Event instead).

---

## 4. Concurrency — Optimistic locking

Every editable entity has a `version` INTEGER column, default 1.
Every PATCH must include the CURRENT version in the request body.
If the submitted version != DB version: 409 Conflict.

Example PATCH /events/{id}:
  Body: { name: "New Name", version: 3 }

  Service logic:
    IF db_event.version != request.version:
      RETURN 409 { error: "stale_version", current_version: db_event.version }
    ELSE:
      UPDATE event SET name=..., version = version + 1 WHERE id = ... AND version = 3
      RETURN updated event with new version

Frontend catches 409, shows: "Event was modified by someone else. Reloading..."
and re-fetches.

---

## 5. Timezones

Stored: ALL timestamps in Postgres as `TIMESTAMPTZ`, inserted as UTC.
Display: client converts to event.venue.timezone, default "Europe/Rome".
Tenant table has a default_timezone field; venues inherit unless overridden.

Cron jobs (auto-end): run in UTC, compare now_utc() > event.ended_at_utc.

---

## 6. API endpoint inventory

### 6.1 Events (/api/v1/events)

| Method | Path                              | Status      | Body              | Returns        |
|--------|-----------------------------------|-------------|-------------------|----------------|
| GET    | /events                           | ✅ built    | -                 | EventResponse[]|
| GET    | /events/{id}                      | ❌ TODO     | -                 | EventResponse  |
| POST   | /events                           | ✅ built    | EventCreate       | EventResponse (201) |
| PATCH  | /events/{id}                      | ❌ TODO     | EventUpdate+ver   | EventResponse  |
| DELETE | /events/{id}                      | ❌ TODO     | -                 | 204 (drafts only)|
| POST   | /events/{id}/activate             | ❌ TODO     | -                 | EventResponse  |
| POST   | /events/{id}/start                | ❌ TODO     | -                 | EventResponse  |
| POST   | /events/{id}/end                  | ❌ TODO     | -                 | EventResponse  |

### 6.2 Bars (/api/v1/events/{event_id}/bars)

| Method | Path                                   | Status | Blocked if Live |
|--------|----------------------------------------|--------|-----------------|
| GET    | /events/{event_id}/bars                | ❌ TODO| no (reads OK)   |
| POST   | /events/{event_id}/bars                | ❌ TODO| yes             |
| PATCH  | /events/{event_id}/bars/{id}           | ❌ TODO| yes             |
| DELETE | /events/{event_id}/bars/{id}           | ❌ TODO| yes             |

### 6.3 Products (/api/v1/events/{event_id}/products)

Single table; `type` field = 'drink' | 'food'.

| Method | Path                                       | Status | Blocked if Live |
|--------|--------------------------------------------|--------|-----------------|
| GET    | /events/{event_id}/products                | ❌ TODO| no              |
| POST   | /events/{event_id}/products                | ❌ TODO| yes             |
| PATCH  | /events/{event_id}/products/{id}           | ❌ TODO| price+name locked, is_archived toggleable |
| DELETE | /events/{event_id}/products/{id}           | ❌ TODO| yes (use archive)|

### 6.4 Dashboard (/api/v1/dashboard)

| Method | Path                               | Returns                                              |
|--------|------------------------------------|------------------------------------------------------|
| GET    | /dashboard/live                    | DashboardLiveResponse (live event + bars + KPIs)     |
| GET    | /dashboard/bars/{bar_id}           | DashboardBarDetailResponse (per-bar drill-down)      |

DashboardLiveResponse logic:
  - Find tenant's single live event (unique index guarantees 0 or 1)
  - IF found: return { event, bars, kpis, alerts, status: 'live' }
  - IF none: find most recently completed event, return { event, summary, status: 'historical' }
  - IF no events ever: return { status: 'empty' }

---

## 7. Response conventions

### 7.1 Success
Every GET/POST/PATCH returns the full resource representation.
POST returns 201 Created.
PATCH returns 200 OK.
DELETE returns 204 No Content.

### 7.2 List endpoints
GET /events returns a plain array for MVP.
Post-Sundance: upgrade to { items, total, page } if > 100 events.

### 7.3 Error envelope
  {
    "error": "short_code",
    "message": "Human sentence",
    "field_errors": { "field": "reason" },
    "current_version": 5,
    "conflicting_event": { "id": "...", "name": "..." }
  }

### 7.4 HTTP status codes
  200  GET succeeded, PATCH succeeded
  201  POST created a new resource
  204  DELETE succeeded
  400  Malformed request (JSON parse error)
  401  No / invalid JWT
  403  Valid JWT, wrong role
  404  Resource does not exist OR wrong tenant
  409  State machine violation OR version mismatch
  422  Pydantic validation failed
  500  Unexpected server error (logged + Sentry)

---

## 8. Database schema changes needed

Compared to current migrations (960521bf64a4 + a1_add_bars):

### 8.1 Add to events table
  version           INTEGER NOT NULL DEFAULT 1
  started_at        TIMESTAMPTZ NULL (set when status -> live)
  ended_at          TIMESTAMPTZ NULL (set when status -> completed)
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()

### 8.2 Add partial unique index
  CREATE UNIQUE INDEX one_live_event_per_tenant
    ON events (tenant_id) WHERE status = 'live';

### 8.3 New table: products
  id            UUID PK
  tenant_id     UUID FK tenants(id) ON DELETE CASCADE
  event_id      UUID FK events(id) ON DELETE CASCADE
  name          TEXT NOT NULL
  type          product_type ENUM ('drink', 'food')
  category      TEXT NOT NULL
  tier          product_tier ENUM ('basic', 'standard', 'premium', 'ultra_premium') NULL
  price_cents   INTEGER NOT NULL CHECK (price_cents >= 0)
  is_archived   BOOLEAN NOT NULL DEFAULT false
  version       INTEGER NOT NULL DEFAULT 1
  created_at    TIMESTAMPTZ DEFAULT now()
  updated_at    TIMESTAMPTZ DEFAULT now()

Price stored as integer cents (never float) to avoid rounding errors.

### 8.4 New table: recipes
  id             UUID PK
  tenant_id      UUID FK tenants(id) ON DELETE CASCADE
  event_id       UUID FK events(id) ON DELETE CASCADE
  product_id     UUID FK products(id) ON DELETE CASCADE
  bottle_type    TEXT NOT NULL
  ml_per_serve   INTEGER NOT NULL CHECK (ml_per_serve > 0)
  bottle_size_ml INTEGER NOT NULL CHECK (bottle_size_ml > 0)

### 8.5 New table: stock_allocations
  id          UUID PK
  tenant_id   UUID FK tenants(id) ON DELETE CASCADE
  event_id    UUID FK events(id) ON DELETE CASCADE
  bar_id      UUID FK bars(id) ON DELETE CASCADE
  product_id  UUID FK products(id) ON DELETE CASCADE
  quantity    INTEGER NOT NULL CHECK (quantity >= 0)
  UNIQUE (bar_id, product_id)

---

## 9. Implementation order

Week 1 (unblocks frontend wiring):
  - Migration: add version, started_at, ended_at, updated_at to events
  - Migration: partial unique index for one_live_event
  - Implement: state_machine.py with allowed_transitions dict
  - Implement: GET /events/{id}
  - Implement: PATCH /events/{id} with version check
  - Implement: POST /events/{id}/activate, /start, /end (idempotent)
  - Implement: DELETE /events/{id} (drafts only, CASCADE)

Week 2:
  - Migration: products, recipes, stock_allocations tables
  - Implement: bars module router (GET, POST, PATCH, DELETE with Live guards)
  - Implement: products module (same pattern, archive instead of delete on Live)

Week 3:
  - Implement: Dashboard module (GET /dashboard/live)
  - Wire Pages A+B+C to real API (replace localStorage with TanStack Query mutations)
  - Verify end-to-end via Claude in Chrome

Week 4 (Sundance prep):
  - Auto-end cron job (checks ended_at hourly)
  - Reports module minimal stub (return event summary JSON)
  - Integration testing

---

## 10. Change log
2026-04-16: v1.0 — 8 scenario decisions locked in from Hesam review.
