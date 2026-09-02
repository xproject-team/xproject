/**
 * Pure selectors for the idle-dashboard season view.
 *
 * Everything here derives from three EXISTING endpoints — no backend
 * work, no invented figures:
 *   /reports/portfolio/kpis  → season totals (owner-only)
 *   /reports                 → per-event revenue rows
 *   /events                  → the next scheduled event
 *
 * Real data only: a selector returns what the API said or nothing.
 * Kept pure so all three dashboard states are unit-testable in the
 * node-only vitest environment.
 */
import type { Event } from '@/lib/mockData'
import type { PortfolioKpis, ReportSummary } from '@/features/reports/useReports'

export type SeasonIdleState = 'loading' | 'first-run' | 'season'

/** Which idle experience to show, from the real KPI response. */
export function seasonIdleState(kpis: PortfolioKpis | undefined): SeasonIdleState {
  if (kpis === undefined) return 'loading'
  return kpis.total_events_completed === 0 ? 'first-run' : 'season'
}

export interface SeasonEventRevenue {
  eventId: string
  name: string
  date: string
  revenue: number
}

/**
 * One revenue row per event from the reports list: the latest READY
 * version wins (a failed regeneration must never eclipse the good
 * number — the C5 rule), one language per event (the IT/EN pair carries
 * identical totals by construction; IT preferred for determinism),
 * ordered by event date.
 */
export function seasonEventRevenues(reports: ReportSummary[]): SeasonEventRevenue[] {
  const byEvent = new Map<string, ReportSummary>()
  for (const r of reports) {
    if (r.status !== 'ready' || r.total_revenue == null) continue
    const current = byEvent.get(r.event_id)
    if (
      current === undefined ||
      r.version > current.version ||
      (r.version === current.version && r.language === 'it' && current.language !== 'it')
    ) {
      byEvent.set(r.event_id, r)
    }
  }
  return [...byEvent.values()]
    .map((r) => ({
      eventId: r.event_id,
      name: r.event_name,
      date: r.event_started_at,
      revenue: Number(r.total_revenue),
    }))
    .filter((row) => !Number.isNaN(row.revenue))
    .sort((a, b) => a.date.localeCompare(b.date))
}

/**
 * The next scheduled event: earliest DRAFT or ACTIVE event with a
 * future scheduled_at. A live event is never "next" (it is the live
 * dashboard's business), completed events are history.
 */
export function pickNextEvent(events: Event[], now: Date): Event | null {
  const upcoming = events
    .filter(
      (e) =>
        (e.status === 'draft' || e.status === 'active') &&
        new Date(e.scheduled_at).getTime() > now.getTime(),
    )
    .sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at))
  return upcoming[0] ?? null
}
