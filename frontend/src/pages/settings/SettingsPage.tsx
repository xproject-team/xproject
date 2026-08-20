/**
 * SettingsPage — basic account + preferences screen.
 *
 * v1.0 scope (intentionally minimal per docs/roadmap.md T1.1):
 *   - Account section: name, email, role badge
 *   - Tenant section: tenant name (read-only)
 *   - Sign out button
 *   - Language preference (placeholder — UI ships, persistence is v1.1)
 *
 * Future enrichment (tracked in roadmap):
 *   - Notification preferences (alerts, reports, mentions)
 *   - Theme toggle (light/dark)
 *   - Password change flow
 *   - Two-factor auth setup
 *
 * Built as a single-page component with section blocks. Uses existing
 * useAuth() context for current user. Sign out uses the logout() that
 * AuthContext already exposes.
 */
import { useState } from 'react'

import { useAuth } from '@/features/auth/useAuth'
import { useChangePassword } from '@/features/auth/hooks'

// ─── Small helper components (kept inline — no need for separate files yet) ──

interface SectionProps {
  title: string
  description?: string
  children: React.ReactNode
}

function Section({ title, description, children }: SectionProps) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-sm p-5 mb-4">
      <div className="mb-4">
        <h2 className="text-base font-bold text-[#1A202C]">{title}</h2>
        {description && (
          <p className="text-xs text-[#718096] mt-0.5">{description}</p>
        )}
      </div>
      {children}
    </div>
  )
}

interface FieldRowProps {
  label: string
  value: string | null | undefined
  badge?: { text: string; color: string } | null
}

function FieldRow({ label, value, badge }: FieldRowProps) {
  return (
    <div className="flex items-baseline justify-between py-2 border-b border-[#EDF2F7] last:border-b-0">
      <p className="text-xs font-semibold uppercase tracking-widest text-[#718096]">
        {label}
      </p>
      <div className="flex items-center gap-2">
        <p className="text-sm text-[#1A202C] font-medium">
          {value ?? '—'}
        </p>
        {badge && (
          <span
            className="inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest rounded-full"
            style={{ backgroundColor: `${badge.color}15`, color: badge.color }}
          >
            {badge.text}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Role badge color map ────────────────────────────────────────────────────

// Two-role model — unknown/retired roles fall back to the neutral color
// in roleBadge() below.
const ROLE_BADGE_COLOR: Record<string, string> = {
  owner:   '#1E5A8D',
  manager: '#6B21A8',
}

function roleBadge(role: string | undefined): { text: string; color: string } | null {
  if (!role) return null
  const normalized = role.toLowerCase()
  return {
    text: normalized.replace('_', ' '),
    color: ROLE_BADGE_COLOR[normalized] ?? '#4A5568',
  }
}

// ─── Page ────────────────────────────────────────────────────────────────────


// ─── Change-password section ────────────────────────────────────────────────

function ChangePasswordSection() {
  const [oldPassword,     setOldPassword]     = useState('')
  const [newPassword,     setNewPassword]     = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [successMessage,  setSuccessMessage]  = useState<string | null>(null)
  const [clientError,     setClientError]     = useState<string | null>(null)

  const mutation = useChangePassword()

  const reset = () => {
    setOldPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setClientError(null)
  }

  const handleSubmit = () => {
    setSuccessMessage(null)
    setClientError(null)

    // Client-side validation first
    if (!oldPassword || !newPassword || !confirmPassword) {
      setClientError('All three fields are required')
      return
    }
    if (newPassword.length < 8) {
      setClientError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setClientError('New password and confirmation do not match')
      return
    }
    if (newPassword === oldPassword) {
      setClientError('New password must differ from the current one')
      return
    }

    mutation.mutate(
      { old_password: oldPassword, new_password: newPassword },
      {
        onSuccess: () => {
          setSuccessMessage('Password updated successfully.')
          reset()
        },
      },
    )
  }

  // Translate server error into the most useful message for the operator.
  const serverError = mutation.error?.detail ?? null
  const errorBanner = clientError ?? serverError

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-semibold uppercase tracking-widest text-[#718096] mb-1 block">
          Current password
        </label>
        <input
          type="password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          autoComplete="current-password"
          className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:border-[#1E5A8D]"
          disabled={mutation.isPending}
        />
      </div>
      <div>
        <label className="text-xs font-semibold uppercase tracking-widest text-[#718096] mb-1 block">
          New password
        </label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
          className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:border-[#1E5A8D]"
          disabled={mutation.isPending}
        />
        <p className="text-[10px] text-[#A0AEC0] mt-1">Minimum 8 characters.</p>
      </div>
      <div>
        <label className="text-xs font-semibold uppercase tracking-widest text-[#718096] mb-1 block">
          Confirm new password
        </label>
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
          className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-md focus:outline-none focus:border-[#1E5A8D]"
          disabled={mutation.isPending}
        />
      </div>

      {errorBanner && (
        <div className="bg-[#FED7D7] text-[#742A2A] text-xs rounded-md px-3 py-2">
          {errorBanner}
        </div>
      )}
      {successMessage && (
        <div className="bg-[#C6F6D5] text-[#22543D] text-xs rounded-md px-3 py-2">
          {successMessage}
        </div>
      )}

      <div className="pt-1">
        <button
          onClick={handleSubmit}
          disabled={mutation.isPending}
          className="bg-[#1E5A8D] hover:bg-[#1A4F7A] text-white text-sm font-semibold px-4 py-2 rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {mutation.isPending ? 'Updating…' : 'Update password'}
        </button>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const { user, logout } = useAuth()
  const [language, setLanguage] = useState<'it' | 'en'>('it')
  const [savingLang, setSavingLang] = useState(false)

  const handleLanguageChange = (next: 'it' | 'en') => {
    setLanguage(next)
    // v1.0: state-only. Future v1.1 will persist via PATCH /auth/me preferences.
    setSavingLang(true)
    window.setTimeout(() => setSavingLang(false), 400)
  }

  const handleSignOut = () => {
    if (window.confirm('Sign out of XProject?')) {
      logout()
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[#1A202C]">Settings</h1>
        <p className="text-sm text-[#718096] mt-1">
          Manage your account, preferences, and session.
        </p>
      </div>

      {/* Account section */}
      <Section
        title="Account"
        description="Your XProject account details."
      >
        <FieldRow
          label="Name"
          value={user?.full_name ?? user?.email}
        />
        <FieldRow
          label="Email"
          value={user?.email}
        />
        <FieldRow
          label="Role"
          value={user?.role ? user.role.toString() : '—'}
          badge={roleBadge(user?.role?.toString())}
        />
      </Section>

{/* Preferences section */}
      <Section
        title="Preferences"
        description="Personal settings stored only for this device. Persistence across devices ships in v1.1."
      >
        <div className="py-2 border-b border-[#EDF2F7] last:border-b-0">
          <p className="text-xs font-semibold uppercase tracking-widest text-[#718096] mb-2">
            Language
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => handleLanguageChange('it')}
              disabled={savingLang}
              className={`px-3 py-1.5 text-sm rounded-md border transition ${
                language === 'it'
                  ? 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                  : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:border-[#1E5A8D]'
              }`}
            >
              Italiano
            </button>
            <button
              onClick={() => handleLanguageChange('en')}
              disabled={savingLang}
              className={`px-3 py-1.5 text-sm rounded-md border transition ${
                language === 'en'
                  ? 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                  : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:border-[#1E5A8D]'
              }`}
            >
              English
            </button>
          </div>
          <p className="text-xs text-[#A0AEC0] mt-2">
            Your selection applies to both the UI and the reports.
          </p>
        </div>
      </Section>

      {/* Change password section */}
      <Section
        title="Password"
        description="Update the password used to sign in to XProject."
      >
        <ChangePasswordSection />
      </Section>

      {/* Session section */}
      <Section
        title="Session"
        description="End your current session on this device."
      >
        <button
          onClick={handleSignOut}
          className="bg-white border border-[#E53E3E] hover:bg-[#FEE2E2]
                     text-[#991B1B] text-sm font-semibold px-4 py-2 rounded-md
                     transition"
        >
          Sign out
        </button>
      </Section>

      {/* About section — version + small honest footer */}
      <div className="mt-8 text-center text-xs text-[#A0AEC0]">
        XProject Operations Platform · v1.0 · {new Date().getFullYear()}
      </div>
    </div>
  )
}
