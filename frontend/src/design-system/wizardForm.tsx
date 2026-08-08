/**
 * Shared dark-theme form primitives for the Create Event wizard.
 *
 * Before this file, `inputCls`/`Label` were copy-pasted verbatim across
 * WizardStep1Basics, WizardStep3Products, WizardStep3Bars,
 * WizardStep4Recharge, and SleshShopPicker. Centralizing them here means
 * the wizard's dark-theme restyle (Day 6) has one source of truth instead
 * of five, and any future tweak doesn't risk drifting between files.
 */
import type { ReactNode } from 'react'

export const inputCls =
  'w-full rounded-[var(--v-radius-sm)] px-3 py-2 text-sm bg-[var(--v-bg-base)] border-[0.5px] border-[var(--v-border)] text-[var(--v-text)] placeholder:text-[var(--v-text-dim)] focus:outline-none focus:ring-2 focus:ring-[var(--v-cyan)]/30 focus:border-[var(--v-cyan)] transition-colors'

/** date / datetime-local inputs — same treatment plus color-scheme:dark
 *  so the native browser picker (day/time popup) renders legibly. */
export const dateInputCls = `${inputCls} [color-scheme:dark]`

export function Label({ children }: { children: ReactNode }) {
  return (
    <label className="block text-[13px] font-medium mb-1" style={{ color: 'var(--v-text)' }}>
      {children}
    </label>
  )
}

export function HelperText({ children }: { children: ReactNode }) {
  return (
    <p className="text-[12px] mt-1" style={{ color: 'var(--v-text-dim)' }}>
      {children}
    </p>
  )
}

/** Step card wrapper — --v-surface, 0.5px --v-border, --v-radius-lg, 24px padding. */
export const stepCardCls =
  'bg-[var(--v-surface)] border-[0.5px] border-[var(--v-border)] rounded-[var(--v-radius-lg)] p-6'

/** Inner row card (one product/bar/station per row) — a level up from the
 *  step card via --v-surface-raised, so rows read as distinct from the
 *  card they sit inside. */
export const rowCardCls =
  'bg-[var(--v-surface-raised)] border-[0.5px] border-[var(--v-border)] rounded-[var(--v-radius)] p-4'

/** Warning/hint banner (amber) — missing category, unlinked Slesh shop, etc. */
export const warningBannerCls =
  'rounded-[var(--v-radius)] p-3'
export const warningBannerStyle = {
  background: 'rgba(255, 216, 77, 0.08)',
  border: '0.5px solid var(--v-amber)',
} as const
