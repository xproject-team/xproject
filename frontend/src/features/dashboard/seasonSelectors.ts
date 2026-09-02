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
 * One revenue row per event from the reports list — drawn from the SAME
 * population the season tiles sum, so bars and tiles can never disagree.
 *
 * /reports/portfolio/kpis sums the latest READY IT report per event.
 * The bars therefore key on (event_id, language), take the latest ready
 * version WITHIN each language (a failed regeneration never eclipses
 * the good number — the C5 rule), and render the IT series. Selecting
 * "latest ready of any language" instead let a higher-version EN row
 * show a different figure than the IT row the endpoint summed — the
 * 2 Sep staging defect, invisible on uniform data where IT == EN by
 * construction. Ordered by event date.
 */
export function seasonEventRevenues(reports: ReportSummary[]): SeasonEventRevenue[] {
  const byEventLanguage = new Map<string, ReportSummary>()
  for (const r of reports) {
    if (r.status !== 'ready' || r.total_revenue == null) continue
    const key = `${r.event_id}::${r.language}`
    const current = byEventLanguage.get(key)
    if (current === undefined || r.version > current.version) {
      byEventLanguage.set(key, r)
    }
  }
  return [...byEventLanguage.values()]
    .filter((r) => r.language === 'it')
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
