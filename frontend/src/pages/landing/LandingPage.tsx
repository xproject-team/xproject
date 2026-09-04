/**
 * LandingPage — the public front door at "/".
 *
 * Audience: investors and grant evaluators. Register: evidence, not
 * advertising — the page shows a system that exists and states its
 * record; every number is real, sourced, and governed (landingFacts.ts;
 * revenue figures structurally reserved, absent until cleared). No CTA
 * beyond sign-in, no pricing, no testimonials, nothing aspirational.
 *
 * Shape (approved 2026-09-04): masthead → definition → proof strip →
 * one merged evidence section (what it does AND the practice proving
 * it, with the in-production fact as a line, never a countable block)
 * → footer.
 *
 * Same standalone token-scope move as the login page: the root carries
 * vera-dark itself. Existing primitives only; the display type sizes
 * are proper extensions of the ramp (components.css), not a parallel
 * scale.
 */
import { Link } from 'react-router-dom'

import { AmbientBackground, Button } from '@/design-system/components'
import '@/design-system/components/components.css'

import { LANDING_FACTS } from './landingFacts'

function Section({
  label,
  children,
  className = 'py-12',
}: {
  label?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={className}>
      {label && <p className="v-label mb-6">{label}</p>}
      {children}
    </section>
  )
}

interface EvidenceBlock {
  title: string
  mechanism: string
  evidence: string
}

// The merged section: each capability stated as mechanism, paired with
// the engineering evidence that it is real. Factual claims only — every
// line is verifiable in this repository or on the running system.
const EVIDENCE: EvidenceBlock[] = [
  {
    title: 'Live point-of-sale ingestion',
    mechanism:
      'Orders stream from the venue POS into an append-only ledger during ' +
      'service — per-line idempotency, refund tracking, and automatic ' +
      'parking of orders from unmapped outlets for operator resolution.',
    evidence:
      'The integration sits behind an adapter contract with two ' +
      'implementations: the production provider, and a provider-shaped ' +
      'simulator that drives the identical pipeline end-to-end in a ' +
      'dedicated staging environment — with the real provider provably ' +
      'unreachable from it.',
  },
  {
    title: 'Stock depletion and alerting',
    mechanism:
      'Adaptive burn-rate forecasting tracks consumption per bar and per ' +
      'product during live service, firing threshold alerts before ' +
      'stock-outs rather than after them.',
    evidence:
      'The alert pipeline is rehearsed against generated event traffic in ' +
      'staging — including the deliberately awkward cases: unmapped ' +
      'outlets, refunded lines, mid-event product changes.',
  },
  {
    title: 'Per-tenant machine learning',
    mechanism:
      'Revenue nowcasting and drinks-demand forecasting, retrained ' +
      'automatically as each event completes, served from versioned model ' +
      'artifacts.',
    evidence:
      'Strict tenant isolation: a tenant without sufficient history gets ' +
      'an honest "insufficient history" — never another tenant’s model. ' +
      'That property is enforced by tests, not convention.',
  },
  {
    title: 'Post-event reporting',
    mechanism:
      'Immutable, versioned reports per event — revenue, stock, guests, ' +
      'forecast accuracy — bilingual, with PDF export. Corrections create ' +
      'new versions; history is never rewritten.',
    evidence:
      'Report revenue is reconciled to the cent against the ' +
      'source-of-record order data, and the platform has run a full ' +
      'season in production for a working venue operation on exactly ' +
      'this discipline.',
  },
]

export default function LandingPage() {
  return (
    <div
      className="vera-dark min-h-screen relative"
      style={{ background: 'var(--v-bg-base)' }}
    >
      <AmbientBackground />

      <div className="relative z-10 max-w-4xl mx-auto px-6">
        {/* ── Masthead ── */}
        <header className="flex items-center justify-between py-6">
          <div>
            <span
              className="text-xl font-bold tracking-tight"
              style={{ color: 'var(--v-text)' }}
            >
              Vera Event
            </span>
          </div>
          <Link to="/login">
            <Button variant="secondary">Sign in</Button>
          </Link>
        </header>

        {/* ── The record, as the headline. Tight bottom: the proof strip
            is the point of the page and must be visible on a laptop
            without scrolling past emptiness (staging review, 4 Sep). ── */}
        <Section className="pt-12 pb-6">
          <h1 className="v-display max-w-2xl">A full season in production.</h1>
          <p className="v-lead max-w-2xl mt-5">
            Vera Event is a live operations platform for event venues:
            point-of-sale ingestion, stock depletion tracking, alerting
            during service, and post-event reporting — one system from the
            first order of the night to the final reconciled report.
          </p>
        </Section>

        {/* ── Proof strip — real, sourced numbers only ── */}
        <Section label="The record" className="pt-4 pb-12">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {LANDING_FACTS.map((fact) => (
              <div
                key={fact.label}
                className="rounded-[var(--v-radius)] p-4 flex flex-col gap-1"
                style={{
                  background: 'var(--v-surface)',
                  border: '0.5px solid var(--v-border)',
                }}
              >
                <span className="v-value tabular-nums">
                  {fact.value.toLocaleString('en-US')}
                </span>
                <span className="v-label">{fact.label}</span>
              </div>
            ))}
          </div>
        </Section>

        {/* ── What it does — and the evidence it does it ── */}
        <Section label="What it does — and the evidence it does it">
          <div className="grid md:grid-cols-2 gap-4">
            {EVIDENCE.map((block) => (
              <div
                key={block.title}
                className="rounded-[var(--v-radius-lg)] p-6"
                style={{
                  background: 'var(--v-surface)',
                  border: '0.5px solid var(--v-border)',
                }}
              >
                <h2
                  className="text-base font-medium mb-2"
                  style={{ color: 'var(--v-text)' }}
                >
                  {block.title}
                </h2>
                <p
                  className="text-sm leading-relaxed"
                  style={{ color: 'var(--v-text-muted)' }}
                >
                  {block.mechanism}
                </p>
                <p
                  className="text-sm leading-relaxed mt-3 pt-3"
                  style={{
                    color: 'var(--v-text-muted)',
                    borderTop: '0.5px solid var(--v-border)',
                  }}
                >
                  <span
                    className="text-[11px] font-medium uppercase tracking-[0.06em] mr-2"
                    style={{ color: 'var(--v-cyan)' }}
                  >
                    Evidence
                  </span>
                  {block.evidence}
                </p>
              </div>
            ))}
          </div>
        </Section>

        {/* ── Footer — the door, and an honest end ── */}
        <footer
          className="py-10 flex items-center justify-between text-sm"
          style={{ borderTop: '0.5px solid var(--v-border)' }}
        >
          <span style={{ color: 'var(--v-text-dim)' }}>Vera Event</span>
          <Link
            to="/login"
            className="transition-colors hover:text-[var(--v-text)]"
            style={{ color: 'var(--v-text-muted)' }}
          >
            Sign in →
          </Link>
        </footer>
      </div>
    </div>
  )
}
