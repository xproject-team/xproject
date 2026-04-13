import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from './useAuth'

// ─── Quick-login accounts (dev shortcut — real prod would remove this) ──

const DEV_ACCOUNTS = [
  { email: 'omar@nomagroup.it',                 password: 'owner123',   label: 'Omar',       role: 'Owner',   color: '#1ABC9C' },
  { email: 'manager.cocktail@nomagroup.it',     password: 'manager123', label: 'M. Cocktail', role: 'Manager', color: '#3498DB' },
  { email: 'manager.focacceria@nomagroup.it',   password: 'manager123', label: 'M. Focacc.', role: 'Manager', color: '#3498DB' },
  { email: 'manager.malandrino@nomagroup.it',   password: 'manager123', label: 'M. Malandr.', role: 'Manager', color: '#3498DB' },
]

// ─── Component ──────────────────────────────────────────────────────────

export function LoginForm() {
  const navigate = useNavigate()
  const { login } = useAuth()

  const [email,    setEmail]    = useState('omar@nomagroup.it')
  const [password, setPassword] = useState('owner123')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(email, password)
      // Owner → /dashboard, Managers also land on /dashboard for the MVP.
      // Later we can branch by role here.
      navigate('/dashboard')
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Sign in failed. Check your credentials and try again.')
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
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Email */}
      <div>
        <label className="block text-sm font-medium text-[#4A5568] mb-1.5" htmlFor="login-email">
          Email
        </label>
        <input
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

      {/* Error */}
      {error && (
        <div className="text-sm text-[#E74C3C] bg-[#FDEDEC] border border-[#E74C3C]/30 rounded-xl px-4 py-2.5">
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

      {/* Dev quick-login shortcuts */}
      <div className="pt-2 border-t border-[#E2E8F0]">
        <p className="text-[10px] font-semibold text-[#718096] uppercase tracking-wide mb-2">
          Quick login (dev)
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
    </form>
  )
}
