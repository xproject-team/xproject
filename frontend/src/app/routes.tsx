import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams} from 'react-router-dom'
import { SessionExpiredModal } from '@/shared/SessionExpiredModal'
import { PermissionDeniedToast } from '@/shared/PermissionDeniedToast'
import { type ReactNode } from 'react'
import { AppShell } from '@/shared/layout/AppShell'
import { EventLayout } from '@/app/EventLayout'
import { useAuth } from '@/features/auth/useAuth'
import { usePermissions, type Permissions } from '@/features/auth/usePermissions'
import { getHomeRoute } from '@/lib/mockUsers'

import LoginPage             from '@/pages/auth/LoginPage'
import DashboardPage         from '@/pages/dashboard/DashboardPage'
import EventListPage         from '@/pages/events/EventListPage'
import EventCreatePage       from '@/pages/events/EventCreatePage'
import EventWizardPage       from '@/pages/events/wizard/EventWizardPage'
import EventDetailPage       from '@/pages/events/EventDetailPage'
import { EventReconciliationPage } from '@/pages/events/EventReconciliationPage'
import ChargeBarsPage        from '@/pages/events/ChargeBarsPage'
import InventoryPage         from '@/pages/inventory/InventoryPage'
import AllocationPage        from '@/pages/inventory/AllocationPage'
import AlertsPage            from '@/pages/alerts/AlertsPage'
import BarsListPage          from '@/pages/bars/BarsListPage'
import BarDetailPage         from '@/pages/bars/BarDetailPage'
import BarCreatePage         from '@/pages/bars/BarCreatePage'
import ProductsListPage      from '@/pages/products/ProductsListPage'
import ProductDetailPage     from '@/pages/products/ProductDetailPage'
import ProductCreatePage     from '@/pages/products/ProductCreatePage'
import CatalogPage           from '@/pages/catalog/CatalogPage'
import RecipeDetailPage      from '@/pages/recipes/RecipeDetailPage'
import RecipeCreatePage      from '@/pages/recipes/RecipeCreatePage'
import WarehousePage          from '@/pages/warehouse/WarehousePage'
import WarehouseScanPage      from '@/pages/warehouse/WarehouseScanPage'
import WarehousePendingReviewPage from '@/pages/warehouse/WarehousePendingReviewPage'
import { BarScanArrivalsPage } from '@/pages/scan/BarScanArrivalsPage'
import { BarScanEmptiesPage } from '@/pages/scan/BarScanEmptiesPage'
import PredictionPage        from '@/pages/predictions/PredictionPage'
import ReportPage            from '@/pages/reports/ReportPage'
import ReportDetailPage      from '@/pages/reports/ReportDetailPage'
import SettingsPage         from '@/pages/settings/SettingsPage'
import ChatPage              from '@/pages/chat/ChatPage'

// ─── Permission flag type ─────────────────────────────────────────────────────
// Extracts only the boolean keys from Permissions so RequirePermission is type-safe.

type BooleanPermissionFlag = {
  [K in keyof Permissions]: Permissions[K] extends boolean ? K : never
}[keyof Permissions]

// ─── Guards ───────────────────────────────────────────────────────────────────

/** Redirects unauthenticated visitors to /login. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  // Wait for AuthProvider to hydrate from /auth/me before deciding to redirect.
  // Without this, hard browser navigation (typed URL or refresh) bounces the
  // user to /login during the async window before fetchCurrentUser resolves.
  if (loading) return null
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  return <>{children}</>
}

/**
 * RequirePermission — checks one or more boolean permission flags.
 * • Single flag:  flag="canCreateEvent"
 * • OR logic:     flag={["canGenerateReport", "canGenerateBarReport"]}
 * If every listed flag is false, redirects to the role's home page.
 */
function RequirePermission({
  flag,
  children,
}: {
  flag: BooleanPermissionFlag | BooleanPermissionFlag[]
  children: ReactNode
}) {
  const { user } = useAuth()
  const perms   = usePermissions()
  const location = useLocation()
  const home    = getHomeRoute(user?.role ?? 'owner')

  const flags     = Array.isArray(flag) ? flag : [flag]
  const permitted = flags.some((f) => perms[f])

  if (!permitted) {
    // Defer the event dispatch to a microtask so it fires AFTER React's
    // render-time work for this component finishes — dispatching during
    // render would warn about state updates in the listener mid-render.
    queueMicrotask(() => {
      window.dispatchEvent(
        new CustomEvent('permission:denied', {
          detail: { attemptedPath: location.pathname },
        }),
      )
    })
    return <Navigate to={home} replace />
  }
  return <>{children}</>
}


// ─── App router ───────────────────────────────────────────────────────────────

// Tiny redirect helper for the legacy /events/:id/edit-v2 URL.
// Reads :id via useParams and sends the browser to /events/:id/edit.
// Written as a component (not a raw <Navigate>) so we can use hooks.
function EditV2Redirect() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/events/${id}/edit`} replace />
}

/**
 * OwnerToEvents — Phase 1 redirect for flat routes shared across roles
 * (event-scoped restructure). Owner now reaches these pages via
 * /events/:id/*, so hitting the old flat URL sends them to the event
 * picker instead. Every other role (Manager, Bartender, Warehouse)
 * keeps using the flat route exactly as before — they don't "enter"
 * an event, they work off whatever's currently live for their bar, so
 * there's nothing to redirect for them.
 */
function OwnerToEvents({ children }: { children: ReactNode }) {
  const perms = usePermissions()
  if (perms.canViewAllBars) return <Navigate to="/events" replace />
  return <>{children}</>
}

export function AppRoutes() {
  return (
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <Routes>
        {/* Public */}
        <Route path="/login" element={<LoginPage />} />

        {/* All authenticated routes wrapped in AppShell */}
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppShell>
                <AuthenticatedRoutes />
              </AppShell>
            </RequireAuth>
          }
        />
      </Routes>
      <SessionExpiredModal />
      <PermissionDeniedToast />
    </BrowserRouter>
  )
}

// ─── Authenticated route tree ─────────────────────────────────────────────────

function AuthenticatedRoutes() {
  const { user } = useAuth()
  const home = getHomeRoute(user?.role ?? 'owner')

  return (
    <Routes>
      {/* Root redirect → role home */}
      <Route path="/" element={<Navigate to={home} replace />} />

      {/*
       * /dashboard
       * Owner (canViewAllBars) · Manager · Bartender (canViewOwnBar) → allowed
       * Warehouse → neither flag is true → redirects to /warehouse
       *
       * Phase 1 (event-scoped restructure): Owner now reaches Dashboard
       * via /events/:id/dashboard, so the flat URL redirects Owner to
       * /events. Manager/Bartender still land on DashboardPage here,
       * unchanged — "My Bar" isn't part of this restructure.
       */}
      <Route
        path="/dashboard"
        element={
          <RequirePermission flag={['canViewAllBars', 'canViewOwnBar']}>
            <OwnerToEvents>
              <DashboardPage />
            </OwnerToEvents>
          </RequirePermission>
        }
      />

      {/*
       * /events — Owner only
       * /events/create must be declared before /events/:id so the static
       * segment "create" is not swallowed by the dynamic :id param.
       */}
      <Route
        path="/events"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventListPage />
          </RequirePermission>
        }
      />
      {/* /events/create — wizard flow (Phase 4 step 10c, Jun 27 2026).
          The old EventCreatePage is now only reachable at
          /events/:id/edit-legacy (kept for StorageTab access). */}
      <Route
        path="/events/create"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventWizardPage />
          </RequirePermission>
        }
      />
      {/* /events/create-v2 → alias for /events/create (bookmark safety).
          Must exist BEFORE /events/:id so "create-v2" is not parsed
          as an event UUID. */}
      <Route
        path="/events/create-v2"
        element={<Navigate to="/events/create" replace />}
      />
      {/*
       * /events/create-v2 \u2014 new 4-step wizard (Phase 4, in development).
       * Runs in PARALLEL with /events/create until the wizard is fully
       * working. Then a swap commit renames this to /events/create and
       * removes the old page. No EventListPage links here yet \u2014 the
       * route is reached by typing the URL during dev/QA.
       */}
      {/*
       * /bars — Owner (canViewAllBars) and Manager
       * Manager sees all bars for the tenant; Bartender sees only their bar
       * via the existing dashboard (BarDashboardView) — not this page.
       */}
      <Route
        path="/bars"
        element={
          <RequirePermission flag="canViewAllBars">
            <BarsListPage />
          </RequirePermission>
        }
      />
      <Route
        path="/bars/new"
        element={
          <RequirePermission flag="canViewAllBars">
            <BarCreatePage />
          </RequirePermission>
        }
      />
      <Route
        path="/bars/:id"
        element={
          <RequirePermission flag="canViewAllBars">
            <BarDetailPage />
          </RequirePermission>
        }
      />
      {/*
       * /products — Owner only (canViewAllBars used as the 'admin-y' gate;
       * Manager and Bartender don't manage product catalog from the UI).
       * /products/new must be declared before /products/:id so the static
       * 'new' segment is not swallowed by the dynamic :id param.
       */}
      <Route
        path="/products"
        element={
          <RequirePermission flag="canViewAllBars">
            <ProductsListPage />
          </RequirePermission>
        }
      />
      <Route
        path="/products/new"
        element={
          <RequirePermission flag="canViewAllBars">
            <ProductCreatePage />
          </RequirePermission>
        }
      />
      <Route
        path="/products/:id"
        element={
          <RequirePermission flag="canViewAllBars">
            <ProductDetailPage />
          </RequirePermission>
        }
      />
      {/*
       * /catalog — Owner-only, so Phase 1 turns this into an
       * unconditional redirect: Catalog now lives at
       * /events/:id/catalog. (Recipe detail/create below stay flat —
       * already orphaned, unlinked from any UI — see CatalogPage.tsx.)
       */}
      <Route
        path="/catalog"
        element={
          <RequirePermission flag="canViewAllBars">
            <Navigate to="/events" replace />
          </RequirePermission>
        }
      />
      <Route
        path="/catalog/recipes/new"
        element={
          <RequirePermission flag="canViewAllBars">
            <RecipeCreatePage />
          </RequirePermission>
        }
      />
      <Route
        path="/catalog/recipes/:id"
        element={
          <RequirePermission flag="canViewAllBars">
            <RecipeDetailPage />
          </RequirePermission>
        }
      />
      {/*
       * /events/:id/* — Phase 1 of the event-scoped restructure.
       * Every event-scoped page now lives under one nested route,
       * wrapped in EventLayout (fetches the event, provides
       * EventContext, renders the "← Back to events" top bar + the
       * event-scoped sidebar). All children are implicitly
       * canCreateEvent-gated (Owner-only) via the parent — every flag
       * these pages used individually (canGenerateReport,
       * canViewPredictions, canViewAllBars, ...) already resolves to
       * "owner only" in usePermissions.ts, so this isn't a widening.
       *
       * / (index)    → redirect to overview
       * /overview    → EventDetailPage (Phase 2 will rename/rebuild this)
       * /edit-v2     → redirect to /edit (bookmark safety, pre-existing)
       *
       * Internal page logic is UNCHANGED — only the mount point moved.
       * EventReconciliationPage and ChargeBarsPage previously read a
       * :event_id param; since the parent route declares :id, their
       * useParams() calls were updated to match (see those files) —
       * a plumbing rename, not a logic change.
       */}
      <Route
        path="/events/:id"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventLayout />
          </RequirePermission>
        }
      >
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<EventDetailPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="catalog" element={<CatalogPage />} />
        <Route path="charge-bars" element={<ChargeBarsPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="warehouse" element={<WarehousePage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="predictions" element={<PredictionPage />} />
        <Route path="reports" element={<ReportPage />} />
        <Route path="reconciliation" element={<EventReconciliationPage />} />
        <Route path="edit" element={<EventWizardPage />} />
        {/* Old EventCreatePage (7-tab layout) — kept as an escape hatch
            because tab 7 (StorageTab) is the sole UI entry point to
            event storage management. Delete after StorageTab is
            relocated (post-Sundance backlog). */}
        <Route path="edit-legacy" element={<EventCreatePage />} />
        <Route path="edit-v2" element={<EditV2Redirect />} />
      </Route>

      {/*
       * /inventory — Owner (canViewAllBars) · Manager/Bartender (canViewOwnBar)
       * Phase 1: Owner now reaches Inventory via /events/:id/inventory;
       * Manager/Bartender keep this flat route unchanged.
       */}
      <Route
        path="/inventory"
        element={
          <RequirePermission flag={['canViewAllBars', 'canViewOwnBar']}>
            <OwnerToEvents>
              <InventoryPage />
            </OwnerToEvents>
          </RequirePermission>
        }
      />

      {/*
       * /inventory/allocate — Owner only (canViewAllBars)
       * Phase C1: starting bottle counts per bar (Sundance 1 manual mode)
       */}
      <Route
        path="/inventory/allocate"
        element={
          <RequirePermission flag="canViewAllBars">
            <AllocationPage />
          </RequirePermission>
        }
      />

      {/*
       * /alerts — Owner + Manager (canSeeOperationalAlerts)
       * Bartender + Warehouse → redirect to home
       * Phase 1: Owner now reaches Alerts via /events/:id/alerts;
       * Manager keeps this flat route unchanged.
       */}
      <Route
        path="/alerts"
        element={
          <RequirePermission flag="canSeeOperationalAlerts">
            <OwnerToEvents>
              <AlertsPage />
            </OwnerToEvents>
          </RequirePermission>
        }
      />

      {/*
       * /warehouse — Owner + Warehouse Staff (canViewWarehouseStock)
       * Manager + Bartender → redirect to home
       * Phase 1: WarehousePage already keys everything off useLiveEvent()
       * (confirmed — it's effectively event-scoped in behavior already,
       * just not in URL), so there's no separate "tenant warehouse"
       * concept to preserve. Owner now reaches it via
       * /events/:id/warehouse; Warehouse staff keep this flat route
       * unchanged (their role has no event picker).
       */}
      <Route
        path="/warehouse"
        element={
          <RequirePermission flag="canViewWarehouseStock">
            <OwnerToEvents>
              <WarehousePage />
            </OwnerToEvents>
          </RequirePermission>
        }
      />

      {/*
       * /warehouse/scan — invoice reconciliation flow.
       * Owner + Warehouse Staff (canViewWarehouseStock).
       * Hosts: invoice picker, create form, scan session UI, discrepancy report.
       */}
      <Route
        path="/warehouse/scan"
        element={
          <RequirePermission flag="canViewWarehouseStock">
            <WarehouseScanPage />
          </RequirePermission>
        }
      />

      {/*
       * /warehouse/pending-review — Owner approves/rejects unexpected scans.
       * Owner-only in practice (only Owner can approve via backend role check)
       * but route gated on canViewWarehouseStock so the link is visible to
       * warehouse staff for diagnostic purposes. Action buttons fail with
       * 403 cleanly for non-Owner roles.
       */}
      <Route
        path="/warehouse/pending-review"
        element={
          <RequirePermission flag="canCreateEvent">
            <WarehousePendingReviewPage />
          </RequirePermission>
        }
      />

      {/*
       * /predictions — Owner only. Phase 1: unconditional redirect —
       * Predictions now lives at /events/:id/predictions.
       */}
      <Route
        path="/predictions"
        element={
          <RequirePermission flag="canViewPredictions">
            <Navigate to="/events" replace />
          </RequirePermission>
        }
      />

      {/*
       * /reports — Owner (canGenerateReport) OR Manager (canGenerateBarReport)
       * Bartender + Warehouse → redirect
       */}
      <Route
        path="/reports"
        element={
          /* Owner-only: ReportPage is the event-wide archive. The
             canGenerateBarReport flag (managers) will gate a separate
             Manager-scoped bar report page when that's built. Until
             then, /reports is Owner-only and Managers redirect to
             /dashboard like every other Owner route. */
          <RequirePermission flag="canGenerateReport">
            <ReportPage />
          </RequirePermission>
        }
      />
      <Route
        path="/reports/:reportId"
        element={
          <RequirePermission flag={['canGenerateReport', 'canGenerateBarReport']}>
            <ReportDetailPage />
          </RequirePermission>
        }
      />

      {/*
       * /chat — Owner + Manager + Bartender (canChat)
       * Warehouse → redirect to /warehouse
       */}
      <Route
        path="/chat"
        element={
          <RequirePermission flag="canChat">
            <ChatPage />
          </RequirePermission>
        }
      />


      {/*
       * /scan/arrivals — Mode B (Manager DISPATCH). Manager + Owner.
       * /scan/empties  — Mode C (Bartender CONSUMED). Bartender + Owner.
       *
       * Backend independently enforces scan_type permissions via the
       * _ROLE_SCAN_PERMISSIONS matrix in scan_service.py (defense in
       * depth — UI gate is convenience, backend is the boundary).
       */}
      <Route
        path="/scan/arrivals"
        element={
          <RequirePermission flag="canScanArrivalsAtBar">
            <BarScanArrivalsPage />
          </RequirePermission>
        }
      />
      <Route
        path="/scan/empties"
        element={
          <RequirePermission flag="canScanEmptiesAtBar">
            <BarScanEmptiesPage />
          </RequirePermission>
        }
      />

      {/* Fallback — any unknown path → role home */}
      {/*
       * /settings — basic account + preferences page.
       * Open to ALL authenticated roles (no permission flag) — every user
       * needs sign out and language toggle.
       */}
      <Route
        path="/settings"
        element={<SettingsPage />}
      />

      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  )
}
