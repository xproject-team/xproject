/**
 * AuthContext — provides current user and auth actions app-wide.
 * Uses mock users in dev; swap login() for JWT decode when backend is ready.
 */
import { createContext, type ReactNode, useState, useEffect } from 'react'
import { type MockUser, getMockUser } from '@/lib/mockUsers'

const STORAGE_KEY = 'xproject_user_id'

interface AuthContextValue {
  user: MockUser | null
  login: (userId: number) => void
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MockUser | null>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const found = getMockUser(Number(stored))
      return found ?? null
    }
    return null
  })

  useEffect(() => {
    if (user) {
      localStorage.setItem(STORAGE_KEY, String(user.id))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [user])

  function login(userId: number) {
    const found = getMockUser(userId)
    if (found) setUser(found)
  }

  function logout() {
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}
