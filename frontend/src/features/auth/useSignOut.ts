/**
 * useSignOut — the ONE sign-out implementation.
 *
 * Before this hook, sign-out logic was independently reimplemented in
 * Sidebar, TopBar (twice: sign-out + switch-role), and SettingsPage —
 * with divergent behavior: SettingsPage never navigated to /login and
 * relied on the route guard catching the cleared session. All call
 * sites now share this.
 *
 *   signOut()    — clear the session, land on /login.
 *   switchRole() — same, but remembers the email so the login form can
 *                  skip straight to the role picker (TopBar's
 *                  switch-role flow).
 *
 * Confirmation UI (SettingsPage's dialog) stays a caller concern —
 * this hook only owns what signing out actually DOES.
 */
import { useNavigate } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'

export function useSignOut() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  function signOut(): void {
    logout()
    navigate('/login')
  }

  function switchRole(): void {
    if (user?.email) {
      try { localStorage.setItem('lastEmail', user.email) } catch { /* quota */ }
    }
    logout()
    navigate('/login')
  }

  return { signOut, switchRole }
}
