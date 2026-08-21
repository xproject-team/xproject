/**
 * SettingsPage — account + session screen.
 *
 * Day 15: converted to the Vera dark design system (PageHeader, Card,
 * Badge, wizardForm inputs, established modal treatment) — the last
 * page off the old light palette.
 *
 * Current scope:
 *   - Account section: name, email, role badge (active session role;
 *     tolerant of unknown/retired role strings — never crashes)
 *   - Password change (F5)
 *   - Sign out (shared useSignOut(), confirmed via the standard modal)
 *
 * The old "Language" preference control was REMOVED, not restyled: it
 * saved nothing (local state + a 400ms fake spinner; no backend column,
 * no endpoint, and nothing that would consume a stored value — the UI
 * has no i18n and report language is chosen per-report). A control that
 * pretends to save is worse than no control. It returns if/when real
 * i18n lands, wired to real persistence.
 */
import { useState } from 'react'

import { Badge, Button, Card, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, HelperText, Label } from '@/design-system/wizardForm'
import { useAuth } from '@/features/auth/useAuth'
import { useSignOut } from '@/features/auth/useSignOut'
import { useChangePassword } from '@/features/auth/hooks'

// ─── Small helper components (kept inline — no need for separate files yet) ──

interface SectionProps {
  title: string
  description?: string
  children: React.ReactNode
}

function Section({ title, description, children }: SectionProps) {
  return (
    <Card className="mb-4">
      <div className="mb-4">
        <h2 className="text-base font-medium" style={{ color: 'var(--v-text)' }}>
          {title}
        </h2>
        {description && (
          <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
            {description}
          </p>
        )}
      </div>
      {children}
    </Card>
  )
}

interface FieldRowProps {
  label: string
  value: string | null | undefined
  badge?: React.ReactNode
}

function FieldRow({ label, value, badge }: FieldRowProps) {
  return (
    <div
      className="flex items-baseline justify-between py-2 last:border-b-0"
      style={{ borderBottom: '0.5px solid var(--v-border)' }}
    >
      <p className="v-label">{label}</p>
      <div className="flex items-center gap-2">
        {value != null && (
          <p className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
            {value}
          </p>
        )}
        {badge ?? (value == null ? (
          <p className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>—</p>
        ) : null)}
      </div>
    </div>
  )
}

// ─── Role badge ──────────────────────────────────────────────────────────────

// Two-role model. Same tolerance pattern as warehouse/roleBadges.ts and
// the alerts page: unknown/retired role strings degrade to a neutral
// badge — never an exhaustive lookup that crashes the page.
const ROLE_BADGE: Record<string, { variant: BadgeVariant; label: string }> = {
  owner:   { variant: 'info',   label: 'Owner' },
  manager: { variant: 'violet', label: 'Manager' },
}

function resolveRoleBadge(role: string | undefined): { variant: BadgeVariant; label: string } | null {
  if (!role) return null
  return ROLE_BADGE[role.toLowerCase()] ?? { variant: 'neutral', label: 'Unknown role' }
}

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
        <Label>Current password</Label>
        <input
          type="password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.target.value)}
          autoComplete="current-password"
          className={inputCls}
          disabled={mutation.isPending}
        />
      </div>
      <div>
        <Label>New password</Label>
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
          className={inputCls}
          disabled={mutation.isPending}
        />
        <HelperText>Minimum 8 characters.</HelperText>
      </div>
      <div>
        <Label>Confirm new password</Label>
        <input
          type="password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
          className={inputCls}
          disabled={mutation.isPending}
        />
      </div>

      {errorBanner && (
        <p className="text-sm" style={{ color: 'var(--v-pink)' }}>
          {errorBanner}
        </p>
      )}
      {successMessage && (
        <p className="text-sm" style={{ color: 'var(--v-green)' }}>
          {successMessage}
        </p>
      )}

      <div className="pt-1">
        <Button variant="primary" onClick={handleSubmit} disabled={mutation.isPending}>
          {mutation.isPending ? 'Updating…' : 'Update password'}
        </Button>
      </div>
    </div>
  )
}

// ─── Sign-out confirmation (established dark modal treatment) ────────────────

function SignOutModal({
  open,
  onCancel,
  onConfirm,
}: {
  open: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        className="rounded-2xl max-w-sm w-full p-6"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
      >
        <h3 className="text-lg font-medium mb-1" style={{ color: 'var(--v-text)' }}>
          Sign out
        </h3>
        <p className="text-sm mb-5" style={{ color: 'var(--v-text-muted)' }}>
          End your current session on this device?
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="secondary"
            onClick={onConfirm}
            style={{ color: 'var(--v-pink)', borderColor: 'rgba(255, 61, 113, 0.4)' }}
          >
            Sign out
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { user } = useAuth()
  const { signOut } = useSignOut()
  const [confirmingSignOut, setConfirmingSignOut] = useState(false)

  // Show the role this SESSION is signed in as (same resolution TopBar
  // uses) — user.role is the legacy field and can differ for a
  // dual-role account.
  const sessionRole = user?.activeRole ?? user?.role
  const badge = resolveRoleBadge(sessionRole?.toString())

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Settings"
          subtitle="Manage your account, password, and session."
        />
      </div>

      {/* Account section */}
      <Section title="Account" description="Your XProject account details.">
        <FieldRow label="Name" value={user?.full_name ?? user?.email} />
        <FieldRow label="Email" value={user?.email} />
        <FieldRow
          label="Role"
          value={null}
          badge={badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : undefined}
        />
      </Section>

      {/* Change password section */}
      <Section title="Password" description="Update the password used to sign in to XProject.">
        <ChangePasswordSection />
      </Section>

      {/* Session section */}
      <Section title="Session" description="End your current session on this device.">
        <Button
          variant="secondary"
          onClick={() => setConfirmingSignOut(true)}
          style={{ color: 'var(--v-pink)', borderColor: 'rgba(255, 61, 113, 0.4)' }}
        >
          Sign out
        </Button>
      </Section>

      {/* About footer */}
      <div className="mt-8 text-center text-xs" style={{ color: 'var(--v-text-dim)' }}>
        XProject Operations Platform · v1.0 · {new Date().getFullYear()}
      </div>

      <SignOutModal
        open={confirmingSignOut}
        onCancel={() => setConfirmingSignOut(false)}
        onConfirm={() => {
          setConfirmingSignOut(false)
          signOut()
        }}
      />
    </div>
  )
}
