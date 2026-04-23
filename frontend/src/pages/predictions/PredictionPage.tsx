/**
 * PredictionPage — demand forecasts for the currently live event.
 *
 * Replaces the 460-line mock scaffold with real backend-wired data:
 *   - Picks the live event via useLiveEvent() (same pattern as Dashboard)
 *   - Fetches the latest prediction for that event
 *   - Renders 3 states honestly:
 *       (a) No active event       → calm message, "Go to Events"
 *       (b) No prediction yet     → "Generate Predictions" CTA
 *       (c) status=insufficient_data → empty state with user message
 *       (d) status=ready          → 5 prediction cards + forecast chart
 *
 * Intentionally REJECTED from the old mockup:
 *   - MOCK_PREDICTIONS hardcoded data (145 units beer, 82% confidence, etc.)
 *     Those numbers were fabricated. The spec rejected synthetic bootstrap
 *     data as a trust violation.
 *   - "AI-generated" / "ML-powered" framing anywhere in the UI. The current
 *     engine is rule-based heuristic math (see docs/predictions-module-spec.md
 *     §2). The page says 'Based on N past events' — honest.
 *
 * Spec: docs/predictions-module-spec.md §3 + §8.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/shared/ui/Button'
import { Card } from '@/shared/ui/Card'
import { useLiveEvent } from '@/features/dashboard/hooks'
import {
  useGeneratePrediction,
  usePredictionForEvent,
  type PredictionCategoryDemand,
  type PredictionData,
  type PredictionRange,
  type PredictionResponse,
  type PredictionRiskFlag,
} from '@/features/predictions/usePredictions'

// ─── Formatting helpers ──────────────────────────────────────────────────────

function fmtEur(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return `€${n.toLocaleString('it-IT', { maximumFractionDigits: 0 })}`
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtInt(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return Math.round(n).toString()
}

// ─── Confidence-tier badge ───────────────────────────────────────────────────

function ConfidenceBadge({
  tier,
  count,
}: {
  tier: 'low' | 'medium' | 'high'
  count: number
}) {
  const config = {
    low:    { bg: '#FEEBC8', text: '#744210', label: 'Low confidence' },
    medium: { bg: '#BEE3F8', text: '#2C5282', label: 'Medium confidence' },
    high:   { bg: '#C6F6D5', text: '#22543D', label: 'High confidence' },
  }[tier]
  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className="inline-flex items-center px-2 py-0.5 rounded-full font-semibold"
        style={{ backgroundColor: config.bg, color: config.text }}
      >
        {config.label}
      </span>
      <span className="text-[#718096]">
        Based on {count} past event{count === 1 ? '' : 's'}
      </span>
    </div>
  )
}

// ─── Range display (low / mid / high with confidence) ────────────────────────

function RangeBlock({
  label,
  range,
  suffix = '',
  icon,
}: {
  label: string
  range: PredictionRange
  suffix?: string
  icon?: string
}) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm">
      <div className="flex items-start justify-between mb-2">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
          {label}
        </p>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <p className="text-3xl font-bold text-[#1A202C] leading-tight">
        {suffix === '€' ? fmtEur(range.mid) : `${fmtInt(range.mid)}${suffix}`}
      </p>
      <p className="text-xs text-[#718096] mt-1">
        Range:{' '}
        {suffix === '€'
          ? `${fmtEur(range.low)} – ${fmtEur(range.high)}`
          : `${fmtInt(range.low)}–${fmtInt(range.high)}${suffix}`}
      </p>
      <div className="flex items-center gap-2 mt-3">
        <div className="flex-1 h-1 bg-[#E2E8F0] rounded-full overflow-hidden">
          <div
            className="h-full bg-[#1E5A8D]"
            style={{ width: `${range.confidence_pct}%` }}
          />
        </div>
        <span className="text-[11px] text-[#718096] font-mono">
          {Math.round(range.confidence_pct)}%
        </span>
      </div>
    </div>
  )
}

// ─── Cards ───────────────────────────────────────────────────────────────────

function RevenueCard({ data }: { data: PredictionData }) {
  const vsLast = data.revenue.vs_last_event_pct
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm">
      <div className="flex items-start justify-between mb-2">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
          Forecast Revenue
        </p>
        <span className="text-lg">💰</span>
      </div>
      <p className="text-3xl font-bold text-[#1A202C] leading-tight">
        {fmtEur(data.revenue.total.mid)}
      </p>
      <p className="text-xs text-[#718096] mt-1">
        Range: {fmtEur(data.revenue.total.low)} – {fmtEur(data.revenue.total.high)}
      </p>
      {vsLast !== null && (
        <p
          className="text-xs font-semibold mt-2"
          style={{ color: vsLast >= 0 ? '#22543D' : '#742A2A' }}
        >
          {vsLast >= 0 ? '↑' : '↓'} {Math.abs(vsLast).toFixed(1)}% vs last event
        </p>
      )}
      <div className="flex items-center gap-2 mt-3">
        <div className="flex-1 h-1 bg-[#E2E8F0] rounded-full overflow-hidden">
          <div
            className="h-full bg-[#1E5A8D]"
            style={{ width: `${data.revenue.total.confidence_pct}%` }}
          />
        </div>
        <span className="text-[11px] text-[#718096] font-mono">
          {Math.round(data.revenue.total.confidence_pct)}%
        </span>
      </div>
    </div>
  )
}

function PeakHourCard({ data }: { data: PredictionData }) {
  if (!data.peak_hour) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-2">
          Peak Hour
        </p>
        <p className="text-sm text-[#A0AEC0] italic">No clear peak detected.</p>
      </div>
    )
  }
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm">
      <div className="flex items-start justify-between mb-2">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
          Peak Hour
        </p>
        <span className="text-lg">🔥</span>
      </div>
      <p className="text-3xl font-bold text-[#1A202C] leading-tight">
        {fmtTime(data.peak_hour.window_start)}
      </p>
      <p className="text-xs text-[#718096] mt-1">
        to {fmtTime(data.peak_hour.window_end)}
      </p>
      <p className="text-xs text-[#4A5568] mt-2">
        <b>~{Math.round(data.peak_hour.predicted_revenue_share_pct)}%</b> of event revenue
      </p>
    </div>
  )
}

function StaffCard({ data }: { data: PredictionData }) {
  return (
    <RangeBlock
      label="Staff Recommendation"
      range={data.staff.total_bartenders}
      suffix=" bartenders"
      icon="👥"
    />
  )
}

// ─── Per-category table ──────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<PredictionCategoryDemand['category'], string> = {
  beer: 'Beer',
  spirits: 'Spirits',
  wine: 'Wine',
  mixers: 'Mixers',
  cocktails: 'Cocktails',
}

const TREND_ICON = { up: '↑', stable: '→', down: '↓' } as const
const TREND_COLOR = { up: '#22543D', stable: '#4A5568', down: '#742A2A' } as const

function CategoryDemandTable({ data }: { data: PredictionData }) {
  if (!data.category_demand.length) return null
  return (
    <Card className="mt-4">
      <h3 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-3">
        Demand by Category
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#E2E8F0]">
            <th className="text-left py-2 pr-3">Category</th>
            <th className="text-right py-2 px-3">Predicted Units</th>
            <th className="text-right py-2 px-3">Range</th>
            <th className="text-right py-2 px-3">Confidence</th>
            <th className="text-center py-2 pl-3">Trend</th>
          </tr>
        </thead>
        <tbody>
          {data.category_demand.map((cat) => (
            <tr
              key={cat.category}
              className="border-b border-[#F1F5F9] last:border-0"
            >
              <td className="py-2 pr-3 text-[#1A202C] font-medium">
                {CATEGORY_LABELS[cat.category]}
              </td>
              <td className="py-2 px-3 text-right text-[#1A202C] font-semibold">
                {fmtInt(cat.units.mid)}
              </td>
              <td className="py-2 px-3 text-right text-[#4A5568]">
                {fmtInt(cat.units.low)}–{fmtInt(cat.units.high)}
              </td>
              <td className="py-2 px-3 text-right text-[#4A5568]">
                {Math.round(cat.units.confidence_pct)}%
              </td>
              <td
                className="py-2 pl-3 text-center font-bold"
                style={{ color: TREND_COLOR[cat.trend] }}
              >
                {TREND_ICON[cat.trend]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

// ─── Risk flags ──────────────────────────────────────────────────────────────

function RiskFlagsCard({ flags }: { flags: PredictionRiskFlag[] }) {
  if (flags.length === 0) {
    return (
      <Card className="mt-4">
        <h3 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-3">
          Stock-Out Risk Flags
        </h3>
        <p className="text-sm text-[#38A169] flex items-center gap-2">
          <span className="text-lg">✓</span>
          No stock-out risks detected — allocation looks safe.
        </p>
      </Card>
    )
  }
  return (
    <Card className="mt-4">
      <h3 className="text-xs font-semibold text-[#718096] uppercase tracking-widest mb-3">
        Stock-Out Risk Flags ({flags.length})
      </h3>
      <div className="space-y-2">
        {flags.map((f) => {
          const pct = Math.round(f.stockout_probability * 100)
          const severity = pct >= 80 ? 'critical' : pct >= 50 ? 'warning' : 'low'
          const bg = severity === 'critical'
            ? '#FED7D7'
            : severity === 'warning'
              ? '#FEEBC8'
              : '#E2E8F0'
          const fg = severity === 'critical'
            ? '#742A2A'
            : severity === 'warning'
              ? '#744210'
              : '#4A5568'
          return (
            <div
              key={`${f.bar_id}-${f.product_id}`}
              className="flex items-center justify-between text-sm border-b border-[#F1F5F9] pb-2 last:border-0"
            >
              <div>
                <p className="font-semibold text-[#1A202C]">{f.product_name}</p>
                <p className="text-xs text-[#718096]">at {f.bar_name}</p>
              </div>
              <span
                className="px-2 py-0.5 rounded-full text-[11px] font-bold"
                style={{ backgroundColor: bg, color: fg }}
              >
                {pct}% risk
              </span>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

// ─── State renderers ─────────────────────────────────────────────────────────

function NoActiveEventState() {
  return (
    <div className="bg-white border border-dashed border-[#CBD5E0] rounded-xl p-12 text-center max-w-xl mx-auto">
      <p className="text-4xl mb-3">📅</p>
      <p className="text-[#4A5568] font-semibold mb-1">
        No active event
      </p>
      <p className="text-xs text-[#718096] max-w-sm mx-auto mb-4">
        Predictions run against a live or upcoming event. Go to the Events page
        to start one, then come back to see the forecast.
      </p>
      <Link
        to="/events"
        className="inline-block bg-[#1E5A8D] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#17456D]"
      >
        Open Events
      </Link>
    </div>
  )
}

function GenerateCtaState({
  onGenerate,
  isPending,
}: {
  onGenerate: () => void
  isPending: boolean
}) {
  return (
    <div className="bg-white border border-dashed border-[#CBD5E0] rounded-xl p-12 text-center max-w-xl mx-auto">
      <p className="text-4xl mb-3">📊</p>
      <p className="text-[#1A202C] font-semibold mb-1">
        Ready to forecast this event
      </p>
      <p className="text-xs text-[#718096] max-w-sm mx-auto mb-5">
        Click below to generate demand predictions based on your completed
        events. The first run takes a few seconds.
      </p>
      <Button variant="primary" size="md" onClick={onGenerate} disabled={isPending}>
        {isPending ? 'Generating…' : '⚡ Generate Predictions'}
      </Button>
    </div>
  )
}

function InsufficientDataState({ message }: { message: string }) {
  return (
    <div className="bg-white border border-dashed border-[#CBD5E0] rounded-xl p-12 text-center max-w-xl mx-auto">
      <p className="text-4xl mb-3">📊</p>
      <p className="text-[#1A202C] font-semibold mb-1">
        Not enough history yet
      </p>
      <p className="text-sm text-[#4A5568] leading-relaxed max-w-md mx-auto mb-4">
        {message}
      </p>
      <p className="text-xs text-[#A0AEC0]">
        Predictions appear automatically once your first event completes.
      </p>
    </div>
  )
}

function FailedState({ reason }: { reason: string | null }) {
  return (
    <div className="bg-[#FED7D7] text-[#742A2A] text-sm rounded-xl p-4 max-w-xl mx-auto">
      <p className="font-semibold mb-1">Prediction failed</p>
      <p className="text-xs">{reason ?? 'Unknown error — try regenerating.'}</p>
    </div>
  )
}

function PendingState() {
  return (
    <div className="text-center py-12 text-sm text-[#A0AEC0]">
      Generating predictions…
    </div>
  )
}

// ─── Ready (the real prediction view) ────────────────────────────────────────

function ReadyState({
  prediction,
  onRegenerate,
  regenPending,
}: {
  prediction: PredictionResponse
  onRegenerate: () => void
  regenPending: boolean
}) {
  const data = prediction.data!
  const generatedAt = useMemo(() => {
    if (!prediction.generated_at) return '—'
    return new Date(prediction.generated_at).toLocaleString('it-IT', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  }, [prediction.generated_at])

  return (
    <>
      {/* Meta row */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <ConfidenceBadge
          tier={data.confidence_tier}
          count={data.based_on_event_count}
        />
        <div className="flex items-center gap-3">
          <span className="text-[11px] text-[#A0AEC0]">
            v{prediction.version} · {generatedAt}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={onRegenerate}
            disabled={regenPending}
          >
            🔄 {regenPending ? 'Regenerating…' : 'Regenerate'}
          </Button>
        </div>
      </div>

      {/* Top 3 cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <RevenueCard data={data} />
        <PeakHourCard data={data} />
        <StaffCard data={data} />
      </div>

      {/* Category demand table */}
      <CategoryDemandTable data={data} />

      {/* Risk flags */}
      <RiskFlagsCard flags={data.risk_flags} />
    </>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function PredictionPage() {
  const { data: liveEvent, isLoading: liveLoading } = useLiveEvent()
  const eventId = liveEvent?.id ?? null

  const {
    data: prediction,
    isLoading: predLoading,
  } = usePredictionForEvent(eventId)

  const generate = useGeneratePrediction()

  const handleGenerate = () => {
    if (!eventId) return
    generate.mutate({ event_id: eventId })
  }
  const handleRegenerate = () => {
    // Regenerate via POST /predictions/generate (idempotency check will
    // skip if nothing changed, but the mutation still invalidates the
    // query so the UI reflects the latest server state).
    if (!eventId) return
    generate.mutate({ event_id: eventId })
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">Demand Predictions</h1>
          <p className="text-sm text-[#718096] mt-1">
            {liveEvent
              ? `Pre-event forecast · ${liveEvent.name}`
              : 'Pre-event forecast based on completed event history'}
          </p>
        </div>
      </div>

      {/* State rendering */}
      {liveLoading && <PendingState />}

      {!liveLoading && !eventId && <NoActiveEventState />}

      {eventId && predLoading && <PendingState />}

      {eventId && !predLoading && !prediction && (
        <GenerateCtaState
          onGenerate={handleGenerate}
          isPending={generate.isPending}
        />
      )}

      {eventId && prediction && prediction.status === 'insufficient_data' && (
        <InsufficientDataState
          message={
            prediction.insufficient_data_message ??
            'Not enough history yet. Complete an event to unlock predictions.'
          }
        />
      )}

      {eventId && prediction && prediction.status === 'failed' && (
        <FailedState reason={prediction.insufficient_data_message} />
      )}

      {eventId && prediction && prediction.status === 'ready' && prediction.data && (
        <ReadyState
          prediction={prediction}
          onRegenerate={handleRegenerate}
          regenPending={generate.isPending}
        />
      )}

      {eventId && prediction && (prediction.status === 'pending' || prediction.status === 'generating') && (
        <PendingState />
      )}
    </div>
  )
}
