/**
 * Display badges for the actor role stamped on a warehouse scan
 * (warehouse_scans.scanned_by_role — an insert-time audit snapshot).
 *
 * READ-SIDE vocabulary: bartender / warehouse_keeper are retired login
 * roles, but historical scans recorded by them still come over the wire
 * and must keep rendering.
 */
import type { ScannerRole } from './useWarehouse'

export interface RoleBadge {
  label: string
  color: string
}

const ROLE_BADGES: Record<ScannerRole, RoleBadge> = {
  owner:            { label: 'Owner',     color: '#1E5A8D' },
  warehouse_keeper: { label: 'Warehouse', color: '#DD6B20' },
  manager:          { label: 'Manager',   color: '#6B21A8' },
  bartender:        { label: 'Bartender', color: '#059669' },
}

/**
 * Resolve the badge for a scan's actor role.
 *
 * Tolerates roles it does not recognise (fallback rendering, not an
 * exhaustive crash) so any later role change degrades to a neutral badge
 * instead of taking the page down.
 */
export function resolveRoleBadge(role: string): RoleBadge {
  const known = (ROLE_BADGES as Record<string, RoleBadge>)[role]
  return known ?? { label: role || 'Unknown', color: '#4A5568' }
}
