import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from './useAuth'

// ─── Quick-login accounts (dev shortcut — hidden in production) ──────────

const DEV_ACCOUNTS = [
  { email: 'omar@nomagroup.it',               password: 'xproject2026', label: 'Omar',        role: 'Owner',     color: '#1E5A8D' },
  { email: 'manager.cocktail@nomagroup.it',   password: 'manager123',   label: 'M. Cocktail', role: 'Manager',   color: '#6B21A8' },
  { email: 'manager.focacceria@nomagroup.it', password: 'manager123',   label: 'M. Focacc.',  role: 'Manager',   color: '#6B21A8' },
  { email: 'manager.malandrino@nomagroup.it', password: 'manager123',   label: 'M. Malandr.', role: 'Manager',   color: '#6B21A8' },
  { email: 'bartender.marco@nomagroup.it',    password: 'bartender123', label: 'Marco',       role: 'Bartender', color: '#059669' },
  { email: 'warehouse.keeper@nomagroup.it',   password: 'warehouse123', label: 'Giorgio',     role: 'Warehouse', color: '#DD6B20' },
]

// Role -> default landing route map. Warehouse staff land on the warehouse
// dashboard since /dashboard isn't usable for that role. Other roles see
// /dashboard which is the operations overview for them.
const LANDING_BY_ROLE: Record<string, string> = {
  owner:      '/dashboard',
  manager:    '/dashboard',
  bartender:  '/dashboard',
  warehouse:  '/warehouse',
}

// ─── Component ───────────────────────────────────────────────────────────

export function LoginForm() {
  const navigate = useNavigate()
  const { login, user } = useAuth()

  // Empty defaults in production. Dev gets the convenience pre-fill via
  // the quick-login buttons (one click instead of one autofill).
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  const emailRef = useRef<HTMLInputElement>(null)
  const isDev = import.meta.env.DEV

  // Focus the email field on mount only. Don't re-fire on error changes
  // — that races with React Router state and can cause unexpected navigation.
  // Post-error focus is handled inline in the catch block via requestAnimationFrame
  // so it runs AFTER React has finished applying the state change.
  useEffect(() => {
    emailRef.current?.focus()
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
      // Role-aware landing. After login() resolves, useAuth().user is
      // populated by AuthProvider on the same tick. Use the new user's
      // role to pick the right landing route.
      const role = user?.role
      const dest = (role && LANDING_BY_ROLE[role]) || '/dashboard'
      navigate(dest)
    } catch (err: unknown) {
      const errResp = err as {
        response?: { data?: { detail?: unknown }; status?: number }
        request?: unknown
      }
      const detail = errResp?.response?.data?.detail
      const status = errResp?.response?.status

      // Pydantic v2 returns 'detail' as an ARRAY of validation-error objects
      // (shape: { type, loc, msg, input }) — NOT a string. Rendering an array/object
      // as a React child crashes the app (the bug we hit on empty-submit).
      // Normalize all shapes into a human string before setError().
      let message: string
      if (typeof detail === 'string') {
        message = detail
      } else if (Array.isArray(detail) && detail.length > 0) {
        // Pydantic 422 — show the first field's message + path. Friendly enough
        // for v1.0; future polish could map field paths to user-facing labels.
        const first = detail[0] as { msg?: string; loc?: unknown[] }
        const fieldPath = Array.isArray(first.loc) ? first.loc.slice(1).join('.') : ''
        message = fieldPath
          ? `${fieldPath}: ${first.msg ?? 'invalid value'}`
          : (first.msg ?? 'Invalid input')
      } else if (status === 422) {
        // 422 with a non-array shape — fallback for safety
        message = 'Invalid email or password format.'
      } else if (errResp?.request) {
        // Request was made but no response — likely network or server down.
        message = "Can't reach the server. Check your connection and try again."
      } else {
        // Setup error or something we didn't anticipate.
        message = 'Sign in failed. Please try again.'
      }
      setError(message)
      // Clear password on error so the user re-enters intentionally.
      // Email stays so they don't have to retype it.
      setPassword('')
      // Defer focus until after React commits the state change. Doing it
      // synchronously can race with router state updates and cause spurious
      // navigation.
      requestAnimationFrame(() => emailRef.current?.focus())
    } finally {
      setLoading(false)
    }
  }

  function applyQuickLogin(acc: (typeof DEV_ACCOUNTS)[number]) {
    setEmail(acc.email)
    setPassword(acc.password)
    setError(null)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      {/* Email */}
      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5" htmlFor="login-email">
          Email
        </label>
        <input
          ref={emailRef}
          id="login-email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-4 py-3 rounded-xl border-2 border-[#E2E8F0] focus:border-[#1E5A8D] focus:outline-none text-sm bg-white"
          placeholder="you@nomagroup.it"
        />
      </div>

      {/* Password */}
      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5" htmlFor="login-password">
          Password
        </label>
        <input
          id="login-password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full px-4 py-3 rounded-xl border-2 border-[#E2E8F0] focus:border-[#1E5A8D] focus:outline-none text-sm bg-white"
          placeholder="••••••••"
        />
      </div>

      {/* Error — announced to screen readers via role=alert + aria-live */}
      {error && (
        <div
          role="alert"
          aria-live="assertive"
          className="text-sm text-[#E74C3C] bg-[#FDEDEC] border border-[#E74C3C]/30 rounded-xl px-4 py-2.5"
        >
          {error}
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={loading}
        className="w-full bg-[#1E5A8D] hover:bg-[#174a78] disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors text-sm shadow-sm"
      >
        {loading ? 'Signing in…' : 'Sign in'}
      </button>

      {/* Forgot password — inert in v1.0 per auth-and-roles-spec §4.3.
          Renders so the affordance exists; full reset flow ships later. */}
      <button
        type="button"
        onClick={() => {
          window.alert(
            'Password reset will be available soon. For now, please contact your tenant admin.',
          )
        }}
        className="block mx-auto text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline"
      >
        Forgot password?
      </button>

      {/* Dev quick-login shortcuts — hidden in production builds */}
      {isDev && (
        <div className="pt-2 border-t border-[#E2E8F0]">
          <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-wide mb-2">
            Quick login (dev only)
          </p>
          <div className="flex flex-wrap gap-1.5">
            {DEV_ACCOUNTS.map((acc) => (
              <button
                key={acc.email}
                type="button"
                onClick={() => applyQuickLogin(acc)}
                className="text-[11px] px-2.5 py-1 rounded-full border bg-white hover:bg-[#F7FAFC] transition-colors"
                style={{ borderColor: `${acc.color}55`, color: acc.color }}
                title={acc.email}
              >
                {acc.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </form>
  )
}
