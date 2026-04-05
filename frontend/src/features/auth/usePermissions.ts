/**
 * usePermissions — derives capability flags from the current user's role.
 * All access-control decisions in the UI go through this hook.
 */
import { useAuth } from './useAuth'

export interface Permissions {
  /** Owner only — full multi-bar overview */
  canViewAllBars: boolean
  /** Manager + Bartender — their assigned bar only */
  canViewOwnBar: boolean
  /** Owner only — anomaly and theft detection flags */
  canSeeAnomalies: boolean
  /** Owner + Manager — operational stock/restock alerts */
  canSeeOperationalAlerts: boolean
  /** Owner only — revenue figures never shown to other roles */
  canSeeRevenue: boolean
  /** Warehouse only — crate/box intake and dispatch scanning */
  canScan: boolean
  /** Bartender only — scanning a bottle when opening it at the bar */
  canScanBottleAtBar: boolean
  /** Owner only — full event report with AI narrative */
  canGenerateReport: boolean
  /** Manager only — their own bar's performance report */
  canGenerateBarReport: boolean
  /** Owner only — ML demand forecasts */
  canViewPredictions: boolean
  /** Owner only — override a model prediction */
  canOverridePrediction: boolean
  /** Owner, Manager, Bartender — not Warehouse */
  canChat: boolean
  /** Owner only */
  canCreateEvent: boolean
  /** Manager only */
  canRequestRestock: boolean
  /** Owner + Warehouse — read-only warehouse stock list */
  canViewWarehouseStock: boolean
  /** Owner only — all bars, all severities including anomaly */
  canViewAllAlerts: boolean
  /** Manager + Bartender: their bar id; Owner + Warehouse: null */
  assignedBarId: number | null
}

export function usePermissions(): Permissions {
  const { user } = useAuth()
  const role = user?.role ?? null

  return {
    canViewAllBars:          role === 'owner',
    canViewOwnBar:           role === 'manager' || role === 'bartender',
    canSeeAnomalies:         role === 'owner',
    canSeeOperationalAlerts: role === 'owner' || role === 'manager',
    canSeeRevenue:           role === 'owner',
    canScan:                 role === 'warehouse',
    canScanBottleAtBar:      role === 'bartender',
    canGenerateReport:       role === 'owner',
    canGenerateBarReport:    role === 'manager',
    canViewPredictions:      role === 'owner',
    canOverridePrediction:   role === 'owner',
    canChat:                 role === 'owner' || role === 'manager' || role === 'bartender',
    canCreateEvent:          role === 'owner',
    canRequestRestock:       role === 'manager',
    canViewWarehouseStock:   role === 'owner' || role === 'warehouse',
    canViewAllAlerts:        role === 'owner',
    assignedBarId:           user?.assignedBarId ?? null,
  }
}
