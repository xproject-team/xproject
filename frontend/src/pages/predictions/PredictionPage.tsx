/**
 * PredictionPage — demand forecasts for the currently live event.
 *
 * Design-system conversion (Day 12 Phase 3): same data/behavior as
 * before (useLiveEvent, usePredictionForEvent, useGeneratePrediction) —
 * UI-only restyle onto the dark design system used by Events/Bars/
 * Catalog/Inventory/Warehouse. No hook, type, or backend change.
 *
 * Renders 5 states honestly, same as before:
 *   (a) No active event       → EmptyState, "Go to Events"
 *   (b) No prediction yet     → EmptyState, "Generate Predictions" CTA
 *   (c) status=insufficient_data → EmptyState explaining what's needed
 *   (d) status=ready          → MetricTiles + category table + risk flags
 *   (e) status=failed         → a distinct (non-EmptyState) error card
 *
 * Two figures on this page are NOT computed from the tenant's data —
 * peak-hour's ~32% revenue share and the "1 bartender per 50 guests"
 * staffing ratio are both fixed constants in predictors/heuristic.py
 * (its own comments: "Track 2 will compute/learn the real value").
 * They're marked with a small muted "Estimate" tag (EstimateTag below)
 * so they don't read with the same authority as the genuinely
 * history-derived numbers next to them.
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

import { useLiveEvent } from '@/features/dashboard/hooks'
import {
  useGeneratePrediction,
  usePredictionForEvent,
  type PredictionCategoryDemand,
  type PredictionData,
  type PredictionResponse,
  type PredictionRiskFlag,
} from '@/features/predictions/usePredictions'
import { Badge, Button, EmptyState, MetricTile, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'

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

// ─── Shared bits ──────────────────────────────────────────────────────────────

/** Marks a figure that is a fixed rule-of-thumb constant, not computed
 * from this tenant's history — peak-hour's ~32% share and the staffing
 * ratio are the two on this page. Deliberately muted/small so it never
 * competes visually with the real, history-derived numbers next to it. */
function EstimateTag() {
  return (
    <p className="text-[10px] mt-1.5 uppercase tracking-wide" style={{ color: 'var(--v-text-dim)' }}>
      Estimate — not computed from your data
    </p>
  )
}

function ConfidenceBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2 mt-2">
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: 'var(--v-surface)' }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'var(--v-cyan)' }} />
      </div>
      <span className="text-[11px] tabular-nums" style={{ color: 'var(--v-text-dim)' }}>
        {Math.round(pct)}%
      </span>
    </div>
  )
}

const CONFIDENCE_TIER_BADGE: Record<'low' | 'medium' | 'high', BadgeVariant> = {
  low: 'warning',
  medium: 'info',
  high: 'success',
}
const CONFIDENCE_TIER_LABEL: Record<'low' | 'medium' | 'high', string> = {
  low: 'Low confidence',
  medium: 'Medium confidence',
  high: 'High confidence',
}

function ConfidenceBadge({ tier, count }: { tier: 'low' | 'medium' | 'high'; count: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <Badge variant={CONFIDENCE_TIER_BADGE[tier]}>{CONFIDENCE_TIER_LABEL[tier]}</Badge>
      <span style={{ color: 'var(--v-text-muted)' }}>
        Based on {count} past event{count === 1 ? '' : 's'}
      </span>
    </div>
  )
}

// ─── Cards (MetricTiles) ──────────────────────────────────────────────────────

function RevenueCard({ data }: { data: PredictionData }) {
  const vsLast = data.revenue.vs_last_event_pct
  const r = data.revenue.total
  return (
    <MetricTile label="Forecast revenue" value={fmtEur(r.mid)} accent="cyan">
      <p className="text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>
        Range: {fmtEur(r.low)} – {fmtEur(r.high)}
      </p>
      {vsLast !== null && (
        <p className="text-xs font-medium mt-1.5" style={{ color: vsLast >= 0 ? 'var(--v-green)' : 'var(--v-pink)' }}>
          {vsLast >= 0 ? '↑' : '↓'} {Math.abs(vsLast).toFixed(1)}% vs last event
        </p>
      )}
      <ConfidenceBar pct={r.confidence_pct} />
    </MetricTile>
  )
}

function PeakHourCard({ data }: { data: PredictionData }) {
  if (!data.peak_hour) {
    return (
      <MetricTile label="Peak hour" value="—">
        <p className="text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>No clear peak detected.</p>
      </MetricTile>
    )
  }
  return (
    <MetricTile
      label="Peak hour"
      value={`${fmtTime(data.peak_hour.window_start)} – ${fmtTime(data.peak_hour.window_end)}`}
      accent="amber"
    >
      <p className="text-xs mt-1" style={{ color: 'var(--v-text-muted)' }}>
        <span style={{ color: 'var(--v-text)', fontWeight: 500 }}>
          ~{Math.round(data.peak_hour.predicted_revenue_share_pct)}%
        </span>{' '}
        of event revenue
      </p>
      <EstimateTag />
    </MetricTile>
  )
}

function StaffCard({ data }: { data: PredictionData }) {
  const r = data.staff.total_bartenders
  return (
    <MetricTile label="Staff recommendation" value={`${fmtInt(r.mid)} bartenders`} accent="violet">
      <p className="text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>
        Range: {fmtInt(r.low)}–{fmtInt(r.high)} bartenders
      </p>
      <ConfidenceBar pct={r.confidence_pct} />
      <EstimateTag />
    </MetricTile>
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
const TREND_COLOR = { up: 'var(--v-green)', stable: 'var(--v-text-dim)', down: 'var(--v-pink)' } as const

function CategoryDemandTable({ data }: { data: PredictionData }) {
  if (!data.category_demand.length) return null
  return (
    <div
      className="overflow-hidden mt-4"
      style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
    >
      <div className="px-5 py-4" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
        <h3 className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>Demand by category</h3>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
            <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Category</th>
            <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Predicted units</th>
            <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Range</th>
            <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Confidence</th>
            <th className="text-center px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Trend</th>
          </tr>
        </thead>
        <tbody>
          {data.category_demand.map((cat) => (
            <tr
              key={cat.category}
              className="transition-colors last:border-0"
              style={{ borderBottom: '0.5px solid var(--v-border)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <td className="px-5 py-3 font-medium" style={{ color: 'var(--v-text)' }}>
                {CATEGORY_LABELS[cat.category]}
              </td>
              <td className="px-5 py-3 text-right tabular-nums font-medium" style={{ color: 'var(--v-text)' }}>
                {fmtInt(cat.units.mid)}
              </td>
              <td className="px-5 py-3 text-right tabular-nums" style={{ color: 'var(--v-text-muted)' }}>
                {fmtInt(cat.units.low)}–{fmtInt(cat.units.high)}
              </td>
              <td className="px-5 py-3 text-right tabular-nums" style={{ color: 'var(--v-text-muted)' }}>
                {Math.round(cat.units.confidence_pct)}%
              </td>
              <td className="px-5 py-3 text-center font-bold" style={{ color: TREND_COLOR[cat.trend] }}>
                {TREND_ICON[cat.trend]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Risk flags ──────────────────────────────────────────────────────────────

function riskSeverity(pct: number): 'critical' | 'warning' | 'low' {
  if (pct >= 80) return 'critical'
  if (pct >= 50) return 'warning'
  return 'low'
}
const RISK_BADGE: Record<'critical' | 'warning' | 'low', BadgeVariant> = {
  critical: 'danger',
  warning: 'warning',
  low: 'neutral',
}

function RiskFlagsCard({ flags }: { flags: PredictionRiskFlag[] }) {
  return (
    <div
      className="p-5 mt-4"
      style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
    >
      <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--v-text)' }}>
        Stock-out risk flags{flags.length > 0 ? ` (${flags.length})` : ''}
      </h3>
      {flags.length === 0 ? (
        <p className="text-sm flex items-center gap-2" style={{ color: 'var(--v-green)' }}>
          <span className="text-base">✓</span>
          No stock-out risks detected — allocation looks safe.
        </p>
      ) : (
        <div className="space-y-2.5">
          {flags.map((f) => {
            const pct = Math.round(f.stockout_probability * 100)
            return (
              <div
                key={`${f.bar_id}-${f.product_id}`}
                className="flex items-center justify-between gap-3 pb-2.5 last:pb-0"
                style={{ borderBottom: '0.5px solid var(--v-border)' }}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: 'var(--v-text)' }}>{f.product_name}</p>
                  <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>at {f.bar_name}</p>
                </div>
                <Badge variant={RISK_BADGE[riskSeverity(pct)]}>{pct}% risk</Badge>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── State renderers ─────────────────────────────────────────────────────────

function NoActiveEventState() {
  return (
    <EmptyState
      headline="No active event"
      body="Predictions run against a live or upcoming event. Go to the Events page to start one, then come back to see the forecast."
      action={
        <Link to="/events">
          <Button variant="primary">Open Events</Button>
        </Link>
      }
    />
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
    <EmptyState
      headline="Ready to forecast this event"
      body="Click below to generate demand predictions based on your completed events. The first run takes a few seconds."
      action={
        <Button variant="primary" onClick={onGenerate} disabled={isPending}>
          {isPending ? 'Generating…' : '+ Generate Predictions'}
        </Button>
      }
    />
  )
}

function InsufficientDataState({ message }: { message: string }) {
  return (
    <EmptyState
      headline="Not enough history yet"
      body={`${message} Predictions appear automatically once your first eligible event completes with recorded sales.`}
    />
  )
}

function FailedState({ reason }: { reason: string | null }) {
  return (
    <div
      className="text-sm p-4 max-w-xl mx-auto rounded-[var(--v-radius)]"
      style={{ background: 'rgba(255, 61, 113, 0.08)', border: '0.5px solid var(--v-pink)', color: 'var(--v-pink)' }}
    >
      <p className="font-medium mb-1">Prediction failed</p>
      <p className="text-xs">{reason ?? 'Unknown error — try regenerating.'}</p>
    </div>
  )
}

function PendingState() {
  return (
    <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
      <div className="inline-flex items-center gap-2">
        <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
        Generating predictions…
      </div>
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
        <ConfidenceBadge tier={data.confidence_tier} count={data.based_on_event_count} />
        <div className="flex items-center gap-3">
          <span className="text-[11px]" style={{ color: 'var(--v-text-dim)' }}>
            v{prediction.version} · {generatedAt}
          </span>
          <Button variant="secondary" onClick={onRegenerate} disabled={regenPending}>
            {regenPending ? 'Regenerating…' : 'Regenerate'}
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
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Demand Predictions"
          subtitle={liveEvent ? `Pre-event forecast · ${liveEvent.name}` : 'Pre-event forecast based on completed event history'}
        />
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
