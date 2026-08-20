/**
 * AuthContext — real JWT-backed auth.
 *
 * login(email, password) → POST /auth/login → store JWT → GET /auth/me → setUser.
 * On page reload, if a JWT is in localStorage, we hydrate user by calling /auth/me.
 * logout() clears the JWT and user state.
 */
import { createContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '@/lib/api'
import { clearToken, getToken, setToken } from '@/lib/auth'

// Two-role model (Phase 2). Retired roles (bartender, warehouse) can still
// appear at RUNTIME from stale tokens or historical data — display code must
// tolerate unknown role strings with fallbacks, never exhaustive lookups.
export type UserRole = 'owner' | 'manager'

export interface AuthUser {
  id:           string
  email:        string
  full_name:    string
  /** Legacy single-role field. Equals activeRole. Kept for backward compat. */
  role:         UserRole
  /** Role this session was logged in as (from JWT active_role claim). */
  activeRole:   UserRole
  /** Every role this user is authorized for (from /auth/roles-for-email). */
  assignedRoles: UserRole[]
  is_active:    boolean
  /** Manager only. Null for Owner. */
  assignedBarId: string | null
}

interface AuthContextValue {
  user:    AuthUser | null
  loading: boolean                                           // true while hydrating on reload
  login:   (email: string, password: string, requestedRole?: UserRole) => Promise<void>
  /** Look up authorized roles for an email (Step 1 of two-step login). */
  rolesForEmail: (email: string) => Promise<UserRole[]>
  logout:  () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

// ─── Helpers ──────────────────────────────────────────────────────────

/** Call /auth/me and build an AuthUser. bar_id comes from the JWT. */
async function fetchCurrentUser(): Promise<AuthUser> {
  const me = await api.get('/auth/me')

  // bar_id + active_role come from JWT claims (not in /me response)
  const token = getToken()
  let assignedBarId: string | null = null
  let activeRole: UserRole = me.data.role  // fallback to legacy claim
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      assignedBarId = payload.bar_id ?? null
      activeRole = (payload.active_role ?? payload.role) as UserRole
    } catch {
      // malformed token — let the user re-login next 401
    }
  }

  // Load every role this user is authorized for. Used by TopBar to decide
  // whether to show the "Switch Role" item in the profile dropdown.
  let assignedRoles: UserRole[] = [activeRole]
  try {
    const r = await api.post('/auth/roles-for-email', { email: me.data.email })
    if (Array.isArray(r.data?.roles) && r.data.roles.length > 0) {
      assignedRoles = r.data.roles as UserRole[]
    }
  } catch {
    // Non-blocking — fall back to just the active role
  }

  return {
    id:            me.data.id,
    email:         me.data.email,
    full_name:     me.data.full_name,
    role:          me.data.role,
    activeRole,
    assignedRoles,
    is_active:     me.data.is_active,
    assignedBarId,
  }
}

// ─── Provider ─────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState<boolean>(true)

  // On mount: if JWT present in localStorage, hydrate user from /auth/me
  useEffect(() => {
    const token = getToken()
    if (!token) {
      setLoading(false)
      return
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => {
        // Token invalid / expired → wipe it
        clearToken()
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  async function login(
    email: string,
    password: string,
    requestedRole?: UserRole,
  ): Promise<void> {
    // OAuth2 password flow — form-encoded body, not JSON
    const form = new URLSearchParams()
    form.append('username', email)      // backend expects 'username' per OAuth2 spec
    form.append('password', password)
    if (requestedRole) {
      form.append('requested_role', requestedRole)
      // Persist last role used so session-expiry re-login can skip the picker
      try { localStorage.setItem('lastRole', requestedRole) } catch { /* quota */ }
    }

    const res = await api.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    setToken(res.data.access_token)

    const current = await fetchCurrentUser()
    setUser(current)
  }

  async function rolesForEmail(email: string): Promise<UserRole[]> {
    const res = await api.post('/auth/roles-for-email', { email })
    return (res.data?.roles ?? []) as UserRole[]
  }

  function logout(): void {
    clearToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, rolesForEmail }}>
      {children}
    </AuthContext.Provider>
  )
}
