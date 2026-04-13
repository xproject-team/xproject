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

export interface AuthUser {
  id:           string
  email:        string
  full_name:    string
  role:         'owner' | 'manager' | 'bartender' | 'warehouse'
  is_active:    boolean
  /** Manager / Bartender only. Null for Owner / Warehouse. */
  assignedBarId: string | null
}

interface AuthContextValue {
  user:    AuthUser | null
  loading: boolean                                           // true while hydrating on reload
  login:   (email: string, password: string) => Promise<void>
  logout:  () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

// ─── Helpers ──────────────────────────────────────────────────────────

/** Call /auth/me and build an AuthUser. bar_id comes from the JWT. */
async function fetchCurrentUser(): Promise<AuthUser> {
  const me = await api.get('/auth/me')

  // bar_id isn't in /auth/me response — decode from JWT claims
  const token = getToken()
  let assignedBarId: string | null = null
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      assignedBarId = payload.bar_id ?? null
    } catch {
      // malformed token — let the user re-login next 401
    }
  }

  return {
    id:            me.data.id,
    email:         me.data.email,
    full_name:     me.data.full_name,
    role:          me.data.role,
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

  async function login(email: string, password: string): Promise<void> {
    // OAuth2 password flow — form-encoded body, not JSON
    const form = new URLSearchParams()
    form.append('username', email)      // backend expects 'username' per OAuth2 spec
    form.append('password', password)

    const res = await api.post('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })

    setToken(res.data.access_token)

    const current = await fetchCurrentUser()
    setUser(current)
  }

  function logout(): void {
    clearToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
