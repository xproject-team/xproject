/**
 * RevenueForecastPanel — the "Forecast" KPI sidebar (Phase E).
 *
 * Right-hand panel next to EventRevenueChart on the Dashboard's Event
 * Revenue card. Renders the nowcast predictor's output (Phase D:
 * GET /events/{id}/revenue-forecast) as four stacked KPI blocks:
 * estimated final revenue + confidence badge, delta vs historical
 * mean, historical range, and a confidence bar.
 *
 * Only ever shown for LIVE events (gated by the caller — see
 * DashboardPage.tsx). Renders a muted empty state on load/error so a
 * flaky forecast endpoint never breaks the surrounding layout.
 */
import type { NowcastConfidenceTier, RevenueForecastResponse } from '@/features/predictions/useRevenueForecast'
import '@/design-system/components/components.css'

export interface RevenueForecastPanelProps {
  forecast: RevenueForecastResponse | null
  loading:  boolean
  error:    Error | null
}

const TIER_COLOR: Record<NowcastConfidenceTier, string> = {
  early:        'var(--v-text-dim)',
  directional:  'var(--v-amber)',
  trustworthy:  'var(--v-green)',
}

const TIER_BADGE_BG: Record<NowcastConfidenceTier, string> = {
  early:        'rgba(107, 114, 128, 0.15)',
  directional:  'rgba(255, 216, 77, 0.12)',
  trustworthy:  'rgba(61, 255, 163, 0.12)',
}

const TIER_LABEL: Record<NowcastConfidenceTier, string> = {
  early:        '~ estimate',
  directional:  'directional',
  trustworthy:  'trustworthy',
}

function formatEur(value: number): string {
  return value.toLocaleString('it-IT', { maximumFractionDigits: 0 })
}

function formatK(value: number): string {
  return (value / 1000).toFixed(1) + 'K'
}

function ConfidenceBadge({ tier }: { tier: NowcastConfidenceTier }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: TIER_BADGE_BG[tier], color: TIER_COLOR[tier] }}
    >
      {TIER_LABEL[tier]}
    </span>
  )
}

function Divider() {
  return <div className="h-px my-3" style={{ background: 'var(--v-border)' }} />
}

// Shared "card title" convention — matches every other panel on the
// Dashboard (Event Revenue, Recharge Desk, Customer Intelligence).
function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="text-[11px] font-semibold tracking-wide uppercase"
      style={{ color: 'var(--v-text-muted)' }}
    >
      {children}
    </span>
  )
}

export function RevenueForecastPanel({ forecast, loading, error }: RevenueForecastPanelProps) {
  const containerClass = 'v-card h-full flex flex-col p-4'

  if (loading && !forecast) {
    return (
      <div className={containerClass}>
        <CardTitle>Forecast</CardTitle>
        <div className="flex-1 flex items-center justify-center text-xs italic" style={{ color: 'var(--v-text-muted)' }}>
          Loading forecast…
        </div>
      </div>
    )
  }

  if (error || !forecast) {
    return (
      <div className={containerClass}>
        <CardTitle>Forecast</CardTitle>
        <div className="flex-1 flex items-center justify-center text-xs italic" style={{ color: 'var(--v-text-muted)' }}>
          Forecast unavailable
        </div>
      </div>
    )
  }

  const {
    predicted_final_revenue_eur,
    confidence,
    confidence_tier,
    vs_historical_avg_eur,
    historical_range_eur,
    historical_n,
  } = forecast

  const isBallpark = confidence < 0.2
  const historicalMean = predicted_final_revenue_eur - vs_historical_avg_eur
  const withinFivePercent =
    historicalMean !== 0 && Math.abs(vs_historical_avg_eur) <= 0.05 * Math.abs(historicalMean)

  const deltaColor = withinFivePercent
    ? 'var(--v-text-dim)'
    : vs_historical_avg_eur >= 0 ? 'var(--v-green)' : 'var(--v-pink)'
  const deltaSign = vs_historical_avg_eur >= 0 ? '+' : '−'

  const confidencePct = Math.round(confidence * 100)

  return (
    <div className={containerClass}>
      <CardTitle>Forecast</CardTitle>

      {/* Est. final — plain --v-text per design-system numeric convention;
          accent color lives on the confidence badge, not the number. */}
      <div className="mt-3">
        <div className="text-[11px]" style={{ color: 'var(--v-text-muted)' }}>Est. final</div>
        <div className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
          {isBallpark ? `~ €${formatEur(predicted_final_revenue_eur)} ballpark` : `€${formatEur(predicted_final_revenue_eur)}`}
        </div>
        <div className="mt-1">
          <ConfidenceBadge tier={confidence_tier} />
        </div>
      </div>

      <Divider />

      {/* vs historical mean */}
      <div>
        <div className="text-[11px]" style={{ color: 'var(--v-text-muted)' }}>vs historical avg</div>
        <div className="text-base font-medium" style={{ color: deltaColor }}>
          {deltaSign}€{formatEur(Math.abs(vs_historical_avg_eur))}
        </div>
      </div>

      <Divider />

      {/* Historical range */}
      <div>
        <div className="text-[11px]" style={{ color: 'var(--v-text-muted)' }}>Historical</div>
        <div className="text-base font-medium" style={{ color: 'var(--v-text)' }}>
          €{formatK(historical_range_eur.min)} – €{formatK(historical_range_eur.max)}
        </div>
        <div className="text-[11px]" style={{ color: 'var(--v-text-dim)' }}>
          n={historical_n} events (2024–25)
        </div>
      </div>

      <Divider />

      {/* Confidence bar */}
      <div>
        <div className="text-[11px] mb-1" style={{ color: 'var(--v-text-muted)' }}>Confidence</div>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--v-border)' }}>
            <div
              className="h-full rounded-full"
              style={{
                width:           `${confidencePct}%`,
                backgroundColor: TIER_COLOR[confidence_tier],
              }}
            />
          </div>
          <span className="text-[11px] tabular-nums w-9 text-right" style={{ color: 'var(--v-text-muted)' }}>
            {confidencePct}%
          </span>
        </div>
      </div>
    </div>
  )
}
