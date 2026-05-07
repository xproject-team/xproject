import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from './useAuth'
import type { UserRole } from './AuthContext'


const ROLE_LANDING: Record<UserRole, string> = {
  owner:     '/dashboard',
  manager:   '/dashboard',
  bartender: '/dashboard',
  warehouse: '/warehouse',
}

const ROLE_LABEL: Record<UserRole, string> = {
  owner:     'Owner',
  manager:   'Manager',
  bartender: 'Bartender',
  warehouse: 'Warehouse Staff',
}

const ROLE_DESCRIPTION: Record<UserRole, string> = {
  owner:     'Full operational control across all bars and events',
  manager:   'Manage one bar during a live event',
  bartender: 'Pour, scan, and track at your bar',
  warehouse: 'Dispatch goods from warehouse to bars',
}

const ROLE_COLOR: Record<UserRole, string> = {
  owner:     '#1E5A8D',
  manager:   '#6B21A8',
  bartender: '#059669',
  warehouse: '#DD6B20',
}

// ─── Component ───────────────────────────────────────────────────────────

type Step = 'email' | 'role' | 'password'

export function LoginForm() {
  const navigate = useNavigate()
  const { login } = useAuth()

  const [step, setStep]                   = useState<Step>('email')
  const [email, setEmail]                 = useState('')
  const [password, setPassword]           = useState('')
  const [selectedRole, setSelectedRole]   = useState<UserRole | null>(null)
  const [loading, setLoading]             = useState(false)
  const [error, setError]                 = useState<string | null>(null)

  const emailRef    = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  // Focus management per step
  useEffect(() => {
    if (step === 'email')    emailRef.current?.focus()
    if (step === 'password') passwordRef.current?.focus()
  }, [step])

  // ─── Step 1: email → role picker (no backend call yet) ──────────────
  // We do NOT query roles-for-email here — that would leak which roles are
  // assigned to which email (account-existence enumeration). The user picks
  // a role they INTEND to use; the backend judges authorization at /login.
  function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email) return
    setError(null)
    setStep('role')
  }

  // ─── Step 2: pick role → go to password ──────────────────────────────
  function handleRolePick(role: UserRole) {
    setSelectedRole(role)
    setStep('password')
    setError(null)
  }

  // ─── Step 3: password → login ────────────────────────────────────────
  async function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedRole) return
    setError(null)
    setLoading(true)
    try {
      await login(email, password, selectedRole)
      // Honor lastPath set by SessionExpiredModal. One-shot restore.
      let dest = ROLE_LANDING[selectedRole]
      try {
        const lastPath = localStorage.getItem('lastPath')
        if (lastPath && lastPath !== '/login') {
          dest = lastPath
          localStorage.removeItem('lastPath')
        }
      } catch { /* storage disabled */ }
      navigate(dest)
    } catch (err: unknown) {
      const errResp = err as {
        response?: { data?: { detail?: unknown }; status?: number }
        request?: unknown
      }
      const status = errResp?.response?.status
      const detail = errResp?.response?.data?.detail

      let message = 'Sign in failed. Please try again.'
      if (status === 401)      message = 'Incorrect email or password.'
      else if (status === 403) message = 'You are not authorized for this role.'
      else if (typeof detail === 'string') message = detail
      else if (errResp?.request) message = "Can't reach the server. Check your connection."

      setError(message)
      setPassword('')
      requestAnimationFrame(() => passwordRef.current?.focus())
    } finally {
      setLoading(false)
    }
  }

  // ─── Back button ─────────────────────────────────────────────────────
  function handleBack() {
    setError(null)
    setPassword('')
    if (step === 'password') {
      setStep('role')
      setSelectedRole(null)
    } else if (step === 'role') {
      setStep('email')
      setSelectedRole(null)
    }
  }


  // ─── Render ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* Step indicator */}
      <div className="flex items-center justify-center gap-2 text-[11px] text-[#718096]">
        <span className={step === 'email' ? 'font-bold text-[#1E5A8D]' : ''}>1. Email</span>
        <span>·</span>
        <span className={step === 'role' ? 'font-bold text-[#1E5A8D]' : ''}>2. Role</span>
        <span>·</span>
        <span className={step === 'password' ? 'font-bold text-[#1E5A8D]' : ''}>3. Password</span>
      </div>

      {/* ─── Step 1: Email ─── */}
      {step === 'email' && (
        <form onSubmit={handleEmailSubmit} className="space-y-5" noValidate>
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

          {error && (
            <div role="alert" aria-live="assertive" className="text-sm text-[#E74C3C] bg-[#FDEDEC] border border-[#E74C3C]/30 rounded-xl px-4 py-2.5">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !email}
            className="w-full bg-[#1E5A8D] hover:bg-[#174a78] disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors text-sm shadow-sm"
          >
            {loading ? 'Checking…' : 'Continue'}
          </button>
        </form>
      )}

      {/* ─── Step 2: Role picker — all 4 roles always visible ─── */}
      {step === 'role' && (
        <div className="space-y-4">
          <div className="text-center">
            <p className="text-base font-semibold text-[#1A202C]">Sign in as</p>
            <p className="text-xs text-[#718096] mt-1 truncate">{email}</p>
          </div>

          <div className="space-y-2.5">
            {(['owner', 'manager', 'bartender', 'warehouse'] as UserRole[]).map((role) => (
              <button
                key={role}
                type="button"
                onClick={() => handleRolePick(role)}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl border-2 border-[#E2E8F0] hover:border-[#1E5A8D] hover:bg-[#F7FAFC] focus:outline-none focus:border-[#1E5A8D] focus:bg-[#F7FAFC] transition-colors text-left"
              >
                <span
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ backgroundColor: ROLE_COLOR[role] }}
                />
                <span className="flex-1 min-w-0">
                  <span className="block font-semibold text-sm text-[#1A202C]">{ROLE_LABEL[role]}</span>
                  <span className="block text-xs text-[#718096] mt-0.5">{ROLE_DESCRIPTION[role]}</span>
                </span>
                <span className="text-[#A0AEC0] text-lg leading-none shrink-0">›</span>
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={handleBack}
            className="block mx-auto text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline"
          >
            ← Back
          </button>
        </div>
      )}

      {/* ─── Step 3: Password ─── */}
      {step === 'password' && selectedRole && (
        <form onSubmit={handlePasswordSubmit} className="space-y-5" noValidate>
          <div className="text-xs text-[#4A5568] bg-[#F7FAFC] rounded-xl px-3 py-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: ROLE_COLOR[selectedRole] }} />
            <span className="font-medium text-[#1A202C]">{email}</span>
            <span className="text-[#CBD5E0]">·</span>
            <span>{ROLE_LABEL[selectedRole]}</span>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#4A5568] mb-1.5" htmlFor="login-password">
              Password
            </label>
            <input
              ref={passwordRef}
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

          {error && (
            <div role="alert" aria-live="assertive" className="text-sm text-[#E74C3C] bg-[#FDEDEC] border border-[#E74C3C]/30 rounded-xl px-4 py-2.5">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="w-full bg-[#1E5A8D] hover:bg-[#174a78] disabled:opacity-60 text-white font-semibold py-3 rounded-xl transition-colors text-sm shadow-sm"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>

          <button
            type="button"
            onClick={handleBack}
            className="block mx-auto text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline"
          >
            ← Back
          </button>
        </form>
      )}

      {/* Forgot password — same as before, available on every step */}
      <button
        type="button"
        onClick={() => window.alert('Password reset will be available soon. For now, please contact your tenant admin.')}
        className="block mx-auto text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline"
      >
        Forgot password?
      </button>

    </div>
  )
}
