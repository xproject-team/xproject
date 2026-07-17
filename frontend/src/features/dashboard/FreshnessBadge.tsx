/**
 * Slesh polling freshness badge.
 *
 * One small pill-shaped tile shown at the top of the BarDashboardView.
 * Day 4 (Jul-19 sprint) rewire: data source moved from GET /pos/freshness
 * (tenant-wide) to GET /events/{event_id}/polling-health (see
 * useFreshness.ts) — same slesh_poll_state row under the hood, but now
 * factors in consecutive_failures via the backend's is_healthy verdict.
 *
 * Three visual states based on is_healthy + seconds_since_last_run:
 *
 *   green  "Polling · synced Xs ago"   (is_healthy && seconds_since < 60)
 *   amber  "Polling · slow · Xs ago"   (is_healthy && seconds_since >= 60)
 *   red    "Polling · stalled · Xs ago" (is_healthy === false)
 *   grey   "Polling not started"       (no slesh_poll_state row yet — 404)
 *
 * Click target: Tooltip that shows last_error for ops debug.
 */
import { useFreshness } from './useFreshness'

function relativeTime(seconds: number | null): string {
  if (seconds === null) return ''
  if (seconds < 60)   return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

export interface FreshnessBadgeProps {
  /**
   * Whether the current event has any Slesh-mapped bars. The badge
   * monitors the Slesh poller — for events with no Slesh integration
   * (manual_bartender flows, simulators, dry runs) the brand-wide
   * poll state is irrelevant and misleading. Hide the badge in
   * those cases.
   */
  eventHasSleshBars: boolean
  /**
   * The event's actual end timestamp (ISO string). When set and in the
   * past, the badge overrides the polling-state display with an "Event
   * ended" message — the poller correctly skips polling for ended
   * events, so the brand-wide freshness signal isn't meaningful.
   */
  eventEndedAt?: string | null
  /** Which event's polling state to show — GET /events/{eventId}/polling-health. */
  eventId: string | null | undefined
}

export function FreshnessBadge({ eventHasSleshBars, eventEndedAt, eventId }: FreshnessBadgeProps) {
  const { data, isLoading } = useFreshness(eventId)

  // No Slesh integration on this event → the polling state is not
  // meaningful here. Hide rather than confuse with "stalled" reads.
  if (!eventHasSleshBars) return null

  // Event has clearly ended → polling correctly skips, but the brand-
  // wide freshness signal would still read "stale". Show the event
  // status explicitly instead of misleading "Polling stalled".
  if (eventEndedAt) {
    const endedAtMs = new Date(eventEndedAt).getTime()
    if (!Number.isNaN(endedAtMs) && endedAtMs < Date.now()) {
      const secondsAgo = Math.floor((Date.now() - endedAtMs) / 1000)
      return (
        <span
          className="inline-flex items-center gap-2 rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600 ring-1 ring-zinc-200"
          title="The event has ended. The Slesh poller correctly skips polling for ended events."
        >
          <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
          Event ended · {relativeTime(secondsAgo)}
        </span>
      )
    }
  }


  if (isLoading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-500">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse" />
        Checking…
      </span>
    )
  }
  // No slesh_poll_state row yet (backend 404s -> useFreshness returns null)
  if (!data) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-600 ring-1 ring-zinc-200">
        <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
        Polling not started
      </span>
    )
  }

  const { last_error, seconds_since_last_run, is_healthy } = data

  // Determine visual variant — green/amber/red per Day 4 spec, keyed off
  // the backend's is_healthy verdict (seconds_since_last_run < 180 AND
  // consecutive_failures < 3) plus a tighter <60s "fully synced" band.
  let variant: 'green' | 'amber' | 'red'
  let label: string

  if (is_healthy && (seconds_since_last_run ?? Infinity) < 60) {
    variant = 'green'
    label = `Polling · synced ${relativeTime(seconds_since_last_run)}`
  } else if (is_healthy) {
    variant = 'amber'
    label = `Polling · slow · ${relativeTime(seconds_since_last_run)}`
  } else {
    variant = 'red'
    label = `Polling · stalled · ${relativeTime(seconds_since_last_run)}`
  }

  const dotColor = {
    green: 'bg-emerald-500',
    amber: 'bg-amber-500',
    red:   'bg-red-500',
  }[variant]

  const bgColor = {
    green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    amber: 'bg-amber-50  text-amber-800   ring-amber-200',
    red:   'bg-red-50    text-red-700     ring-red-200',
  }[variant]

  const animate = variant === 'green' ? 'animate-pulse' : ''

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs ring-1 ${bgColor}`}
      title={last_error ? `Error: ${last_error}` : "Live order data status. Green = streaming from Slesh POS. Red = not yet connected (sandbox credentials pending)."}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotColor} ${animate}`} />
      {label}
    </span>
  )
}
