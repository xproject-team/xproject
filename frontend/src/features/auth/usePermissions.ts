/**
 * usePermissions — derives capability flags from the current user's role.
 * All access-control decisions in the UI go through this hook.
 *
 * Two-role model (Phase 2): owner and manager. Every flag is an explicit
 * equality check — no fallback buckets — so a stale token carrying a
 * retired role gets no capabilities rather than surprise ones.
 */
import { useAuth } from './useAuth'

export interface Permissions {
  /** Owner only — full multi-bar overview */
  canViewAllBars: boolean
  /** Manager — their assigned bar only */
  canViewOwnBar: boolean
  /** Owner only — anomaly and theft detection flags */
  canSeeAnomalies: boolean
  /** Owner + Manager — operational stock/restock alerts */
  canSeeOperationalAlerts: boolean
  /** Owner only — revenue figures never shown to other roles */
  canSeeRevenue: boolean
  /** Manager + Owner — DISPATCH scanning at the bar */
  canScanArrivalsAtBar: boolean
  /** Manager + Owner — CONSUMED scanning at the bar (absorbed from the retired Bartender role) */
  canScanEmptiesAtBar:  boolean
  /** Owner only — full event report with AI narrative */
  canGenerateReport: boolean
  /** Manager only — their own bar's performance report */
  canGenerateBarReport: boolean
  /** Owner only — ML demand forecasts */
  canViewPredictions: boolean
  /** Owner only — override a model prediction */
  canOverridePrediction: boolean
  /** Owner + Manager */
  canChat: boolean
  /** Owner only */
  canCreateEvent: boolean
  /** Manager only */
  canRequestRestock: boolean
  /** Owner + Manager — warehouse stock views and invoice lifecycle */
  canViewWarehouseStock: boolean
  /** Owner only — all bars, all severities including anomaly */
  canViewAllAlerts: boolean
  /** Manager: their bar id; Owner: null */
  assignedBarId: string | null
}

export function usePermissions(): Permissions {
  const { user } = useAuth()
  const role = user?.role ?? null

  return {
    canViewAllBars:          role === 'owner',
    canViewOwnBar:           role === 'manager',
    canSeeAnomalies:         role === 'owner',
    canSeeOperationalAlerts: role === 'owner' || role === 'manager',
    canSeeRevenue:           role === 'owner',
    canScanArrivalsAtBar:    role === 'manager' || role === 'owner',
    canScanEmptiesAtBar:     role === 'manager' || role === 'owner',
    canGenerateReport:       role === 'owner',
    canGenerateBarReport:    role === 'manager',
    canViewPredictions:      role === 'owner',
    canOverridePrediction:   role === 'owner',
    canChat:                 role === 'owner' || role === 'manager',
    canCreateEvent:          role === 'owner',
    canRequestRestock:       role === 'manager',
    canViewWarehouseStock:   role === 'owner' || role === 'manager',
    canViewAllAlerts:        role === 'owner',
    assignedBarId:           user?.assignedBarId ?? null,
  }
}
