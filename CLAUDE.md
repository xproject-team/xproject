# CLAUDE.md — XProject Master Context

## What Is This Project?
XProject is an AI-powered operational intelligence platform for hospitality events (300+ guests).
It integrates POS systems (Slesh NFC wristbands), ML-based demand prediction, anomaly detection,
barcode/QR warehouse tracking, and role-based dashboards.
Target: Sundance event, June 2026. Team: Hesam (Backend/ML/DevOps) + Reza (Frontend).

## Architecture: Modular Monolith
This is NOT microservices. One FastAPI app, one PostgreSQL database, one Docker image.
Module boundaries are enforced by directory structure. Any module can be extracted later.

## Backend 4-Layer Architecture (STRICT RULES)
- **Router Layer** (router.py): HTTP handling + input validation ONLY. No business logic. Parse request → call service → return response.
- **Service Layer** (service.py): ALL business logic. Never imports from Router. Never writes SQL directly.
- **Repository Layer** (repository.py): ALL database queries. Pure data access. No business logic.
- **Core Layer** (app/core/): Shared infrastructure. Imported by all layers. Imports nothing from modules.

## Backend Directory Structure (Backend Bible Section 2.3 — FOLLOW EXACTLY)
```
backend/
  app/
    __init__.py
    main.py                          ← FastAPI app factory + health check
    core/                            ← Shared infrastructure
      __init__.py
      config.py                      ← Pydantic Settings from .env
      database.py                    ← Async SQLAlchemy engine + session
      redis_client.py                ← aioredis connection + pub/sub helpers
      security.py                    ← bcrypt hashing, JWT create/decode
      dependencies.py                ← get_db, get_current_user, require_role
      exceptions.py                  ← NotFoundError, PermissionDeniedError + handlers
      middleware.py                  ← CORS, request_id, request logging
    modules/                         ← Business domains
      events/
        __init__.py, models.py, schemas.py, service.py, repository.py, router.py
      inventory/
        __init__.py, models.py, schemas.py, service.py, repository.py, router.py
      pos/
        __init__.py, service.py, router.py
        adapters/
          __init__.py, base.py, slesh.py  ← POS adapter pattern
      alerts/
        __init__.py, models.py, schemas.py, service.py, engine.py, router.py
        ← engine.py = alert evaluation logic (unique to this module)
      predictions/
        __init__.py, models.py, schemas.py, service.py, features.py, ml_model.py, router.py
        ← features.py = feature engineering, ml_model.py = model loading/inference
      anomaly/
        __init__.py, models.py, schemas.py, service.py, router.py
        detectors/
          __init__.py                ← Statistical anomaly detection algorithms
      warehouse/
        __init__.py, models.py, schemas.py, service.py, barcode.py, router.py
        ← barcode.py = barcode/QR scan logic
      reports/
        __init__.py, models.py, schemas.py, service.py, narrative.py, pdf.py, router.py
        ← narrative.py = AI-generated event narrative, pdf.py = PDF export
      auth/
        __init__.py, models.py, schemas.py, service.py, router.py
      chat/
        __init__.py, models.py, schemas.py, service.py, router.py
    realtime/                        ← WebSocket + Pub/Sub
      __init__.py, websocket.py, manager.py, publisher.py
    workers/                         ← Background jobs (arq)
      __init__.py, scheduler.py, tasks.py
    scripts/                         ← Utilities
      __init__.py, seed.py
  tests/
    __init__.py, conftest.py
  requirements.txt
  Dockerfile
  alembic.ini
  alembic/                           ← Database migrations
```

## Frontend Directory Structure (Frontend Bible Section 1.3 — FOLLOW EXACTLY)
```
frontend/
  src/
    app/                             ← App shell, routing, providers
      App.tsx, routes.tsx, providers.tsx
    pages/                           ← One file per route (THIN: layout + composition only)
      auth/LoginPage.tsx
      events/EventListPage.tsx, EventCreatePage.tsx, EventDetailPage.tsx
      dashboard/DashboardPage.tsx, BarDetailPage.tsx
      warehouse/WarehouseScanPage.tsx, WarehouseInventoryPage.tsx
      predictions/PredictionPage.tsx
      reports/ReportPage.tsx
      settings/SettingsPage.tsx
    features/                        ← Feature modules (business logic + UI)
      auth/useAuth.ts, AuthContext.tsx, LoginForm.tsx
      events/useEvents.ts, EventForm.tsx, EventCard.tsx
      dashboard/useDashboard.ts, BarCard.tsx, BarGrid.tsx, StatsStrip.tsx
      inventory/useInventory.ts, StockTable.tsx, RateChart.tsx
      alerts/useAlerts.ts, AlertPanel.tsx, AlertToast.tsx
      warehouse/useWarehouse.ts, ScannerView.tsx, ScanHistory.tsx
      predictions/usePredictions.ts, ForecastCard.tsx, TicketChart.tsx
      reports/useReports.ts, NarrativeSection.tsx, MetricsGrid.tsx
      chat/useChat.ts, ChatPanel.tsx, MessageBubble.tsx
    shared/                          ← Reusable components (NO business logic)
      ui/Button, Card, Badge, Modal, Spinner, EmptyState, Table
      layout/AppShell, Sidebar, TopBar, PageHeader
      charts/LineChart, BarChart, DonutChart (Recharts wrappers)
    lib/                             ← Infrastructure
      api.ts                         ← Axios instance + auth interceptor
      ws.ts                          ← WebSocket hook with reconnection
      auth.ts                        ← Token storage, decode, refresh
      types.ts                       ← TypeScript interfaces (MUST mirror Pydantic schemas)
      utils.ts                       ← Formatting helpers (currency, dates, %)
    assets/                          ← Static files, icons, fonts
  package.json
  tsconfig.json
  vite.config.ts
  Dockerfile
```

## Technology Stack
### Backend
- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy 2.0 (async), Alembic (migrations)
- PostgreSQL 16, Redis 7
- arq (background job queue)
- Pydantic v2 (schemas + settings)
- python-jose (JWT), passlib + bcrypt (passwords)

### Frontend
- React 18, TypeScript 5.4+, Vite 5
- Tailwind CSS 3.4+
- TanStack Query 5 (server state)
- Zustand 4 (client state: activeEventId, sidebarCollapsed, darkMode)
- React Router 6 (nested routes, protected routes)
- React Hook Form + Zod (forms, validation mirrors Pydantic)
- Recharts 2 (charts), date-fns 3 (dates)
- Axios 1 (HTTP client with interceptors)
- html5-qrcode 2 (barcode scanner)
- Native WebSocket (custom hook with exponential backoff)

## Docker Services (5 total)
1. **db** — postgres:16-alpine (port 5432)
2. **redis** — redis:7-alpine with AOF persistence (port 6379)
3. **api** — FastAPI with uvicorn --reload (port 8000)
4. **web** — React with Vite dev server (port 3000)
5. **worker** — Same image as api, runs arq background jobs

## Design System Colors (Frontend Bible Section 4.1)
- Primary: #1E5A8D (navigation, headers, primary buttons)
- Accent: #6C63FF (active states, selection, progress bars)
- Success: #38A169 (healthy status, positive trends)
- Warning: #D69E2E (warning alerts, approaching thresholds)
- Danger: #E53E3E (critical alerts, stock-outs, negative anomalies)
- Background: #F7FAFC, Surface: #FFFFFF
- Text Primary: #1A202C, Text Secondary: #4A5568, Border: #E2E8F0

## API Contract Rules
- 37 endpoints across: Auth, Events, Inventory, POS, Alerts, Warehouse, Predictions, Reports, Chat, Restock, WebSocket
- Pydantic schemas (backend) and TypeScript interfaces (frontend) MUST match exactly
- Use snake_case for ALL field names (both Python and TypeScript)
- Python `datetime` → TypeScript `string` (ISO format)
- Python `Optional[X]` → TypeScript `X?`
- Python `list[X]` → TypeScript `X[]`

## 4 User Roles
1. **Owner** (Omar) — sees everything, all dashboards, reports, predictions
2. **Manager** — sees assigned bar only, limited dashboard, receives alerts
3. **Bartender** — sees own bar inventory only
4. **Warehouse** — sees warehouse scan interface only

## Key Architectural Rules
- Pages are THIN: import feature components, pass props, handle layout. No business logic.
- Features own their API calls: each feature has a useXxx.ts hook wrapping TanStack Query.
- Components NEVER call axios directly — always through hooks.
- No prop drilling beyond 2 levels — use context or Zustand store.
- WebSocket is ONE global connection per event via useDashboardWS() hook.
- Backend modules communicate via direct function calls (not HTTP — this is a monolith).

## Code Standards
- Python: Type hints everywhere. Ruff for linting. Async where beneficial.
- TypeScript: Strict mode. No `any` types. Interfaces for objects.
- Commits: `feat(module): description`, `fix(module): description`, `docs: description`
- Branch naming: `feature/module-name`, `fix/issue-description`
