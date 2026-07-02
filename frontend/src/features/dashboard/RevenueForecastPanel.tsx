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

export interface RevenueForecastPanelProps {
  forecast: RevenueForecastResponse | null
  loading:  boolean
  error:    Error | null
}

const TIER_COLOR: Record<NowcastConfidenceTier, string> = {
  early:        '#A0AEC0',
  directional:  '#DD8B3B',
  trustworthy:  '#38A169',
}

const TIER_BADGE_BG: Record<NowcastConfidenceTier, string> = {
  early:        'bg-[#A0AEC0]/15',
  directional:  'bg-[#DD8B3B]/15',
  trustworthy:  'bg-[#38A169]/15',
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
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${TIER_BADGE_BG[tier]}`}
      style={{ color: TIER_COLOR[tier] }}
    >
      {TIER_LABEL[tier]}
    </span>
  )
}

function Divider() {
  return <div className="h-px bg-[#E2E8F0] my-3" />
}

export function RevenueForecastPanel({ forecast, loading, error }: RevenueForecastPanelProps) {
  const containerClass =
    'border border-[#E2E8F0] rounded-lg bg-white p-4 shadow-sm h-full flex flex-col'

  if (loading && !forecast) {
    return (
      <div className={containerClass}>
        <span className="text-[11px] font-semibold tracking-wide text-[#A0AEC0] uppercase">
          Forecast
        </span>
        <div className="flex-1 flex items-center justify-center text-xs text-[#A0AEC0] italic">
          Loading forecast…
        </div>
      </div>
    )
  }

  if (error || !forecast) {
    return (
      <div className={containerClass}>
        <span className="text-[11px] font-semibold tracking-wide text-[#A0AEC0] uppercase">
          Forecast
        </span>
        <div className="flex-1 flex items-center justify-center text-xs text-[#A0AEC0] italic">
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
    ? '#A0AEC0'
    : vs_historical_avg_eur >= 0 ? '#38A169' : '#E53E3E'
  const deltaSign = vs_historical_avg_eur >= 0 ? '+' : '−'

  const confidencePct = Math.round(confidence * 100)

  return (
    <div className={containerClass}>
      <span className="text-[11px] font-semibold tracking-wide text-[#A0AEC0] uppercase">
        Forecast
      </span>

      {/* Est. final */}
      <div className="mt-3">
        <div className="text-[11px] text-[#A0AEC0]">Est. final</div>
        {isBallpark ? (
          <div className="text-xl font-bold text-[#A0AEC0]">
            ~ €{formatEur(predicted_final_revenue_eur)} ballpark
          </div>
        ) : (
          <div className="text-xl font-bold text-[#1E5A8D]">
            €{formatEur(predicted_final_revenue_eur)}
          </div>
        )}
        <div className="mt-1">
          <ConfidenceBadge tier={confidence_tier} />
        </div>
      </div>

      <Divider />

      {/* vs historical mean */}
      <div>
        <div className="text-[11px] text-[#A0AEC0]">vs historical avg</div>
        <div className="text-base font-semibold" style={{ color: deltaColor }}>
          {deltaSign}€{formatEur(Math.abs(vs_historical_avg_eur))}
        </div>
      </div>

      <Divider />

      {/* Historical range */}
      <div>
        <div className="text-[11px] text-[#A0AEC0]">Historical</div>
        <div className="text-base font-semibold text-[#2E4B7A]">
          €{formatK(historical_range_eur.min)} – €{formatK(historical_range_eur.max)}
        </div>
        <div className="text-[11px] text-[#A0AEC0]">
          n={historical_n} events (2024–25)
        </div>
      </div>

      <Divider />

      {/* Confidence bar */}
      <div>
        <div className="text-[11px] text-[#A0AEC0] mb-1">Confidence</div>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 rounded-full bg-[#E2E8F0] overflow-hidden">
            <div
              className="h-full rounded-full"
              style={{
                width:           `${confidencePct}%`,
                backgroundColor: TIER_COLOR[confidence_tier],
              }}
            />
          </div>
          <span className="text-[11px] text-[#A0AEC0] tabular-nums w-9 text-right">
            {confidencePct}%
          </span>
        </div>
      </div>
    </div>
  )
}
