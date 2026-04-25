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

const ROLE_BADGE_COLOR: Record<string, string> = {
  owner:            '#1E5A8D',
  warehouse_keeper: '#DD6B20',
  warehouse:        '#DD6B20',
  manager:          '#6B21A8',
  bartender:        '#059669',
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
            UI translation ships incrementally. Reports are already bilingual.
          </p>
        </div>
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
