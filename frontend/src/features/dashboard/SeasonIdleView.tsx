/**
 * SeasonIdleView — what the dashboard shows when no event is LIVE.
 *
 * Replaces the old "No Live event in progress / Go to Events" empty
 * state with the real season: total revenue, event count, per-night
 * comparison, the strongest night, and what's next. Three data sources,
 * all pre-existing endpoints (no backend work): portfolio KPIs and the
 * reports list (both owner-only — the fetches are gated on
 * canSeeRevenue, and managers get the next-event view without season
 * financials), plus the events list for "what's next".
 *
 * REAL DATA ONLY. Every figure is the API's own number; anything
 * unavailable omits its element. The average is labelled exactly what
 * the endpoint computes — revenue per EVENT. No per-guest or per-order
 * figure exists at season level without backend work, so none is shown.
 *
 * A tenant with no completed events gets a first-run state written as a
 * beginning, not an absence — a second client's first login lands here.
 */
import { useNavigate } from 'react-router-dom'

import { Button, Card, MetricTile } from '@/design-system/components'
import { usePermissions } from '@/features/auth/usePermissions'
import { useEvents } from '@/features/events/hooks'
import { usePortfolioKpis, useReports } from '@/features/reports/useReports'
import type { Event } from '@/lib/mockData'

import {
  pickNextEvent,
  seasonEventRevenues,
  seasonIdleState,
} from './seasonSelectors'

// File-local formatters, matching the codebase convention (backlog A1).
function fmtEur(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = typeof value === 'string' ? Number(value) : value
  if (Number.isNaN(n)) return '—'
  return `€${n.toLocaleString('it-IT', { maximumFractionDigits: 0 })}`
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('it-IT', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  })
}

function daysUntil(iso: string, now: Date): number {
  return Math.ceil((new Date(iso).getTime() - now.getTime()) / 86_400_000)
}

// ─── Next event card (both roles) ────────────────────────────────────────────

function NextEventCard({ next, now }: { next: Event; now: Date }) {
  const navigate = useNavigate()
  const days = daysUntil(next.scheduled_at, now)
  return (
    <Card>
      <p className="v-label mb-2">Next event</p>
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
            {next.name}
          </p>
          <p className="text-sm mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
            {fmtDate(next.scheduled_at)}
            <span style={{ color: 'var(--v-text-dim)' }}>
              {' '}· in {days} {days === 1 ? 'day' : 'days'}
            </span>
          </p>
        </div>
        <Button variant="secondary" onClick={() => navigate(`/events/${next.id}`)}>
          View event
        </Button>
      </div>
    </Card>
  )
}

// ─── Per-event revenue comparison (same bar idiom as the report page) ────────

function SeasonBars({
  rows,
  bestEventName,
}: {
  rows: ReturnType<typeof seasonEventRevenues>
  bestEventName: string | null
}) {
  const max = Math.max(...rows.map((r) => r.revenue), 0)
  if (max <= 0) return null
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const strongest = r.name === bestEventName
        return (
          <div key={r.eventId} className="flex items-center gap-3">
            <span
              className="w-40 shrink-0 truncate text-sm"
              style={{ color: strongest ? 'var(--v-text)' : 'var(--v-text-muted)' }}
              title={r.name}
            >
              {r.name}
            </span>
            <div
              className="flex-1 h-2 rounded-full overflow-hidden"
              style={{ background: 'var(--v-surface-raised)' }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${(r.revenue / max) * 100}%`,
                  background: strongest ? 'var(--v-cyan)' : 'var(--v-border-hover)',
                }}
              />
            </div>
            <span
              className="w-20 shrink-0 text-right text-sm tabular-nums"
              style={{ color: 'var(--v-text)' }}
            >
              {fmtEur(r.revenue)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── The idle view ───────────────────────────────────────────────────────────

export function SeasonIdleView() {
  const navigate = useNavigate()
  const { canSeeRevenue } = usePermissions()
  const now = new Date()

  // Season endpoints are owner-only — never fired for managers.
  const kpisQuery = usePortfolioKpis({ enabled: canSeeRevenue })
  const reportsQuery = useReports(canSeeRevenue ? { limit: 50 } : undefined, {
    enabled: canSeeRevenue,
  })
  const eventsQuery = useEvents()

  const next = pickNextEvent(eventsQuery.data ?? [], now)

  // ── Manager: what's next, no season financials (reports are owner-only) ──
  if (!canSeeRevenue) {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-4">
        <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>
          No event is live right now. The dashboard comes alive when one starts.
        </p>
        {next && <NextEventCard next={next} now={now} />}
      </div>
    )
  }

  const state = seasonIdleState(kpisQuery.data)

  if (state === 'loading') {
    return (
      <div
        className="flex items-center justify-center h-full text-sm"
        style={{ color: 'var(--v-text-muted)' }}
      >
        Loading the season…
      </div>
    )
  }

  // ── First run: a beginning, not an absence ──
  if (state === 'first-run') {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-4">
        <Card className="!p-8">
          <p className="v-label mb-2">Your season starts here</p>
          <p className="text-xl font-medium mb-2" style={{ color: 'var(--v-text)' }}>
            Welcome to Vera Event
          </p>
          <p className="text-sm max-w-lg" style={{ color: 'var(--v-text-muted)' }}>
            When your first event goes live, this dashboard tracks it in real
            time — sales, stock, and alerts as they happen. After it wraps,
            the season builds here: revenue night by night, your strongest
            event, and what's next.
          </p>
          {!next && (
            <div className="mt-5">
              <Button variant="primary" onClick={() => navigate('/events/create')}>
                Plan your first event
              </Button>
            </div>
          )}
        </Card>
        {next && <NextEventCard next={next} now={now} />}
      </div>
    )
  }

  // ── The season ──
  const kpis = kpisQuery.data!
  const rows = seasonEventRevenues(reportsQuery.data ?? [])

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-medium" style={{ color: 'var(--v-text)' }}>
            Season overview
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
            No event is live right now — this is the season so far.
          </p>
        </div>
        <Button variant="ghost" onClick={() => navigate('/reports')}>
          All reports →
        </Button>
      </div>

      {/* Season strip — every figure is the API's own number. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricTile
          label="Season revenue"
          value={fmtEur(kpis.lifetime_revenue)}
          accent="cyan"
        />
        <MetricTile
          label="Events completed"
          value={String(kpis.total_events_completed)}
        />
        {/* Labelled exactly what the endpoint computes: per event. */}
        <MetricTile label="Avg revenue / event" value={fmtEur(kpis.avg_event_revenue)} />
        {kpis.best_event_name && (
          <MetricTile label="Strongest event" value={kpis.best_event_name}>
            {kpis.best_event_revenue != null && (
              <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
                {fmtEur(kpis.best_event_revenue)}
              </span>
            )}
          </MetricTile>
        )}
      </div>

      {next && <NextEventCard next={next} now={now} />}

      {rows.length > 0 && (
        <Card>
          <p className="v-label mb-3">Revenue by event</p>
          <SeasonBars rows={rows} bestEventName={kpis.best_event_name} />
        </Card>
      )}
    </div>
  )
}
