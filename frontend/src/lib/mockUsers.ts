/**
 * Mock users for development — replace with real JWT auth when backend is ready.
 * No personal names or emails; roles only.
 *
 * Bar assignment trick: LoginPage calls setPendingBar() before login(userId).
 * getMockUser() picks it up once and clears it, so AuthContext stores the
 * full user object (including bar) without needing its signature changed.
 */

// Two-role model (Phase 2): owner and manager only.
export type UserRole = 'owner' | 'manager'

export interface MockUser {
  id: string
  /** Role label — used by Sidebar / TopBar for display. No personal names. */
  name: string
  role: UserRole
  color: string
  assignedBarId?: string
  assignedBarName?: string
}

export const MOCK_USERS: MockUser[] = [
  { id: 'usr-1', name: 'Owner',   role: 'owner',   color: '#1ABC9C' },
  { id: 'usr-2', name: 'Manager', role: 'manager', color: '#3498DB' },
]

export const BARS = [
  { id: 'bar-1', name: 'Main Bar' },
  { id: 'bar-2', name: 'VIP Lounge' },
  { id: 'bar-3', name: 'Pool Bar' },
  { id: 'bar-4', name: 'DJ Booth' },
] as const

// ─── Pending bar assignment ───────────────────────────────────────────────────
// LoginPage sets this before calling login(userId); getMockUser consumes it once.

let _pendingBar: { barId: string; barName: string } | null = null

export function setPendingBar(barId: string, barName: string): void {
  _pendingBar = { barId, barName }
}

export function getMockUser(id: string): MockUser | undefined {
  const base = MOCK_USERS.find((u) => u.id === id)
  if (!base) return undefined

  if (_pendingBar && base.role === 'manager') {
    const result: MockUser = {
      ...base,
      assignedBarId:   _pendingBar.barId,
      assignedBarName: _pendingBar.barName,
    }
    _pendingBar = null // consume once
    return result
  }

  return base
}

/** First route after login, by role. Keep /dashboard as fallback — routes.tsx depends on this. */
export function getHomeRoute(_role: UserRole): string {
  return '/dashboard'
}
