/**
 * LoginForm — the three-step sign-in flow: email → role → password.
 *
 * Restyled 2026-09-04 to the Vera design system (the last pre-redesign
 * surface). RULING HONORED: markup and classNames only — every handler,
 * the login call, the lastPath restore, and the focus management are
 * behaviourally identical to the pre-restyle version. The error mapping
 * and back-transition were mechanically EXTRACTED into exported pure
 * functions (identical output for every input) so the flow's behaviour
 * is pinned by tests the node-only vitest environment can run.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Badge, Button } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label } from '@/design-system/wizardForm'

import { useAuth } from './useAuth'
import type { UserRole } from './AuthContext'


export const ROLE_LANDING: Record<UserRole, string> = {
  owner:   '/dashboard',
  manager: '/dashboard',
}

export const ROLE_LABEL: Record<UserRole, string> = {
  owner:   'Owner',
  manager: 'Manager',
}

export const ROLE_DESCRIPTION: Record<UserRole, string> = {
  owner:   'Full operational control across all bars and events',
  manager: 'Manage one bar during a live event',
}

// Role identity follows the app-wide badge convention (Settings, TopBar):
// owner = cyan/info, manager = violet.
const ROLE_BADGE: Record<UserRole, 'info' | 'violet'> = {
  owner:   'info',
  manager: 'violet',
}

type Step = 'email' | 'role' | 'password'

/** Backwards through the step machine; email is the floor. Extracted
 *  from handleBack — the state clearing stays in the component. */
export function loginStepBack(step: Step): Step {
  if (step === 'password') return 'role'
  if (step === 'role') return 'email'
  return 'email'
}

/** The status→message mapping, extracted byte-identical from the old
 *  handlePasswordSubmit catch block. Every sign-in error state. */
export function loginErrorMessage(err: unknown): string {
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
  return message
}

// ─── Small presentational pieces ─────────────────────────────────────────

// Errors use the codebase's established idiom — plain --v-pink text, as
// in every converted page and modal (CopyRecipesModal, SignOutModal,
// ReportPage). Deliberately NOT a new boxed component: a shared
// AlertBanner is a design-system decision, recorded on the backlog,
// not a side effect of restyling one page.
function ErrorAlert({ message }: { message: string }) {
  return (
    <p
      role="alert"
      aria-live="assertive"
      className="text-sm"
      style={{ color: 'var(--v-pink)' }}
    >
      {message}
    </p>
  )
}

function Spinner() {
  return (
    <svg
      className="w-4 h-4 animate-spin"
      fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round" strokeLinejoin="round"
        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
      />
    </svg>
  )
}

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="block mx-auto text-xs transition-colors hover:text-[var(--v-text)]"
      style={{ color: 'var(--v-text-muted)' }}
    >
      ← Back
    </button>
  )
}

// ─── Component ───────────────────────────────────────────────────────────

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
      // Honor lastPath set by SessionExpiredModal. One-shot restore with TTL.
      // Format: JSON {path, ts} written by SessionExpiredModal. We restore
      // only if ts is within 30 min — older entries are treated as stale
      // (e.g. user closed the laptop overnight and re-opened in the morning;
      // they should land on the role default, not where they were yesterday).
      const LAST_PATH_TTL_MS = 30 * 60 * 1000  // 30 minutes
      let dest = ROLE_LANDING[selectedRole]
      try {
        const raw = localStorage.getItem('lastPath')
        if (raw) {
          localStorage.removeItem('lastPath')  // one-shot regardless of validity
          try {
            const parsed = JSON.parse(raw) as { path?: string; ts?: number }
            const age = Date.now() - (parsed.ts ?? 0)
            if (
              parsed.path &&
              parsed.path !== '/login' &&
              age >= 0 &&
              age < LAST_PATH_TTL_MS
            ) {
              dest = parsed.path
            }
          } catch {
            // Old-format bare string (pre-TTL deploy) — ignore as stale.
          }
        }
      } catch { /* storage disabled */ }
      navigate(dest)
    } catch (err: unknown) {
      setError(loginErrorMessage(err))
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
    setStep(loginStepBack(step))
    if (step === 'password' || step === 'role') setSelectedRole(null)
  }


  // ─── Render ──────────────────────────────────────────────────────────
  return (
    <div className="space-y-5">

      {/* Step indicator — the redesign's label voice, active step in cyan */}
      <div
        className="flex items-center justify-center gap-2 text-[11px] font-medium uppercase tracking-[0.06em]"
        style={{ color: 'var(--v-text-dim)' }}
      >
        {(['email', 'role', 'password'] as const).map((s, i) => (
          <span key={s} className="flex items-center gap-2">
            {i > 0 && <span>·</span>}
            <span style={step === s ? { color: 'var(--v-cyan)' } : undefined}>
              {i + 1}. {s === 'email' ? 'Email' : s === 'role' ? 'Role' : 'Password'}
            </span>
          </span>
        ))}
      </div>

      {/* ─── Step 1: Email ─── */}
      {step === 'email' && (
        <form onSubmit={handleEmailSubmit} className="space-y-5" noValidate>
          <div>
            <Label>Email</Label>
            <input
              ref={emailRef}
              id="login-email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputCls}
              placeholder="you@example.com"
            />
          </div>

          {error && <ErrorAlert message={error} />}

          <Button
            type="submit"
            variant="primary"
            disabled={loading || !email}
            className="w-full"
          >
            Continue
          </Button>
        </form>
      )}

      {/* ─── Step 2: Role picker — Owner and Manager only ─── */}
      {step === 'role' && (
        <div className="space-y-4">
          <div className="text-center">
            <p className="text-base font-medium" style={{ color: 'var(--v-text)' }}>
              Sign in as
            </p>
            <p className="text-xs mt-1 truncate" style={{ color: 'var(--v-text-muted)' }}>
              {email}
            </p>
          </div>

          <div className="space-y-2.5">
            {(['owner', 'manager'] as UserRole[]).map((role) => (
              <button
                key={role}
                type="button"
                onClick={() => handleRolePick(role)}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-[var(--v-radius)] text-left transition-colors hover:bg-white/[0.04] focus:outline-none focus:ring-2 focus:ring-[var(--v-cyan)]/30"
                style={{
                  background: 'var(--v-surface)',
                  border: '0.5px solid var(--v-border)',
                }}
              >
                <Badge variant={ROLE_BADGE[role]}>{ROLE_LABEL[role]}</Badge>
                <span className="flex-1 min-w-0">
                  <span
                    className="block text-xs"
                    style={{ color: 'var(--v-text-muted)' }}
                  >
                    {ROLE_DESCRIPTION[role]}
                  </span>
                </span>
                <span
                  className="text-lg leading-none shrink-0"
                  style={{ color: 'var(--v-text-dim)' }}
                >
                  ›
                </span>
              </button>
            ))}
          </div>

          <BackLink onClick={handleBack} />
        </div>
      )}

      {/* ─── Step 3: Password ─── */}
      {step === 'password' && selectedRole && (
        <form onSubmit={handlePasswordSubmit} className="space-y-5" noValidate>
          {/* Identity chip: who is signing in, as what */}
          <div
            className="flex items-center gap-2 rounded-[var(--v-radius-sm)] px-3 py-2 text-xs"
            style={{
              background: 'var(--v-surface)',
              border: '0.5px solid var(--v-border)',
            }}
          >
            <Badge variant={ROLE_BADGE[selectedRole]}>{ROLE_LABEL[selectedRole]}</Badge>
            <span className="truncate font-medium" style={{ color: 'var(--v-text)' }}>
              {email}
            </span>
          </div>

          <div>
            <Label>Password</Label>
            <input
              ref={passwordRef}
              id="login-password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputCls}
              placeholder="••••••••"
            />
          </div>

          {error && <ErrorAlert message={error} />}

          <Button
            type="submit"
            variant="primary"
            disabled={loading || !password}
            className="w-full"
          >
            {loading ? (
              <>
                <Spinner />
                Signing in…
              </>
            ) : (
              'Sign in'
            )}
          </Button>

          <BackLink onClick={handleBack} />
        </form>
      )}

      {/* Forgot password — same behaviour as before, available on every step */}
      <button
        type="button"
        onClick={() => window.alert('Password reset will be available soon. For now, please contact your tenant admin.')}
        className="block mx-auto text-xs transition-colors hover:text-[var(--v-text)]"
        style={{ color: 'var(--v-text-dim)' }}
      >
        Forgot password?
      </button>

    </div>
  )
}
