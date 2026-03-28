/**
 * AuthContext — provides current user and auth actions app-wide.
 * JWT is stored and decoded via lib/auth.ts; axios interceptors auto-attach it.
 */
import { createContext, type ReactNode, useState } from 'react'

interface AuthUser {
  id: string
  email: string
  role: 'owner' | 'manager' | 'bartender' | 'warehouse'
}

interface AuthContextValue {
  user: AuthUser | null
  login: (token: string) => void
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)

  function login(token: string) {
    // TODO: decode JWT, set user, store token via lib/auth.ts
  }

  function logout() {
    setUser(null)
    // TODO: clear token from storage
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}
