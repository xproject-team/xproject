import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { SessionExpiredModal } from '@/shared/SessionExpiredModal'
import { PermissionDeniedToast } from '@/shared/PermissionDeniedToast'
import { type ReactNode } from 'react'
import { AppShell } from '@/shared/layout/AppShell'
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
       */}
      <Route
        path="/dashboard"
        element={
          <RequirePermission flag={['canViewAllBars', 'canViewOwnBar']}>
            <DashboardPage />
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
      <Route
        path="/events/create"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventCreatePage />
          </RequirePermission>
        }
      />
      {/*
       * /events/create-v2 \u2014 new 4-step wizard (Phase 4, in development).
       * Runs in PARALLEL with /events/create until the wizard is fully
       * working. Then a swap commit renames this to /events/create and
       * removes the old page. No EventListPage links here yet \u2014 the
       * route is reached by typing the URL during dev/QA.
       */}
      <Route
        path="/events/create-v2"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventWizardPage />
          </RequirePermission>
        }
      />
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
       * /catalog — unified Products + Recipes admin page (Owner).
       * Top-tabbed shell that mounts ProductsListPage and RecipesListPage.
       * Detail/create pages for products keep their /products/* routes;
       * recipes get their own /catalog/recipes/* segment so the user can
       * always tell which entity they\'re editing from the URL alone.
       */}
      <Route
        path="/catalog"
        element={
          <RequirePermission flag="canViewAllBars">
            <CatalogPage />
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
       * /events/:id/edit — Create Event wizard in edit mode (DRAFT events)
       */}
      <Route
        path="/events/:id/edit"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventCreatePage />
          </RequirePermission>
        }
      />
      <Route
        path="/events/:id"
        element={
          <RequirePermission flag="canCreateEvent">
            <EventDetailPage />
          </RequirePermission>
        }
      />
      <Route
        path="/events/:event_id/reconciliation"
        element={
          <RequirePermission flag="canGenerateReport">
            <EventReconciliationPage />
          </RequirePermission>
        }
      />

      {/*
       * /inventory — Owner only (canViewAllBars)
       */}
      <Route
        path="/inventory"
        element={
          <RequirePermission flag={['canViewAllBars', 'canViewOwnBar']}>
            <InventoryPage />
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
       */}
      <Route
        path="/alerts"
        element={
          <RequirePermission flag="canSeeOperationalAlerts">
            <AlertsPage />
          </RequirePermission>
        }
      />

      {/*
       * /warehouse — Owner + Warehouse Staff (canViewWarehouseStock)
       * Manager + Bartender → redirect to home
       */}
      <Route
        path="/warehouse"
        element={
          <RequirePermission flag="canViewWarehouseStock">
            <WarehousePage />
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
       * /predictions — Owner only
       */}
      <Route
        path="/predictions"
        element={
          <RequirePermission flag="canViewPredictions">
            <PredictionPage />
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
