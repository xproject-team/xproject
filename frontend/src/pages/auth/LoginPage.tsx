/**
 * LoginPage — the product's front door, in the product's own visual
 * language.
 *
 * The design tokens are scoped to `.vera-dark`, which only AppShell
 * applies — and /login renders outside the shell, which is why this
 * page stayed on the pre-redesign style through the eleven-page
 * conversion. The fix is the same standalone-scope move the
 * design-system preview route uses: this page's root carries the class
 * itself.
 *
 * Card treatment follows the codebase's established modal recipe
 * (surface-raised, 0.5px border, rounded-2xl) — deliberately not glass;
 * the ambient washes behind it are the app's own static AmbientBackground
 * (no animation, no movement). Auth logic lives in LoginForm, untouched.
 */
import { AmbientBackground } from '@/design-system/components'
import '@/design-system/components/components.css'

import { LoginForm } from '@/features/auth/LoginForm'

export default function LoginPage() {
  return (
    <div
      className="vera-dark min-h-screen flex flex-col items-center justify-center px-4 py-10 relative"
      style={{ background: 'var(--v-bg-base)' }}
    >
      <AmbientBackground />

      <main className="relative z-10 w-full max-w-md flex flex-col items-center">
        {/* The mark — the product's identity, not a deployment's */}
        <div className="text-center mb-8">
          <p
            className="text-2xl font-bold tracking-tight"
            style={{ color: 'var(--v-text)' }}
          >
            Vera Event
          </p>
          <p
            className="text-[11px] font-medium uppercase tracking-[0.14em] mt-1.5"
            style={{ color: 'var(--v-cyan)' }}
          >
            Event operations intelligence
          </p>
        </div>

        {/* The sign-in card — the established modal surface */}
        <div
          className="w-full rounded-2xl p-8"
          style={{
            background: 'var(--v-surface-raised)',
            border: '0.5px solid var(--v-border)',
          }}
        >
          <LoginForm />
        </div>
      </main>
    </div>
  )
}
