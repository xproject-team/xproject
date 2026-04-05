/**
 * useAuth — hook that exposes the current auth state from AuthContext.
 * Components read user, role, login(), and logout() through this hook.
 */
import { useContext } from 'react'
import { AuthContext } from './AuthContext'

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
