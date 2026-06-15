/**
 * Slesh polling freshness badge.
 *
 * One small pill-shaped tile shown at the top of the BarDashboardView.
 * Three visual states based on backend's is_live + is_stale + last_status:
 *
 *   green  "Live · synced Ns ago"            (is_live && last_status=ok)
 *   yellow "Sync delayed · Nm ago"           (status=error, or stale<5m)
 *   red    "Polling stalled · Nm ago"        (is_stale or status=circuit_open)
 *   grey   "Polling not started"             (has_state=false — first ever run)
 *
 * Click target: Tooltip that shows last_error + brand_id for ops debug.
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
}

export function FreshnessBadge({ eventHasSleshBars, eventEndedAt }: FreshnessBadgeProps) {
  const { data, isLoading } = useFreshness()

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
  if (!data) {
    return null
  }

  const { has_state, last_status, last_error, seconds_since, is_live, is_stale } = data

  // Determine visual variant
  let variant: 'green' | 'yellow' | 'red' | 'grey' = 'grey'
  let label = 'Polling not started'

  if (!has_state) {
    variant = 'grey'
    label = 'Polling not started'
  } else if (is_live) {
    variant = 'green'
    label = `Live · synced ${relativeTime(seconds_since)}`
  } else if (last_status === 'circuit_open' || is_stale) {
    variant = 'red'
    label = `Polling stalled · ${relativeTime(seconds_since)}`
  } else if (last_status === 'error') {
    variant = 'yellow'
    label = `Sync delayed · ${relativeTime(seconds_since)}`
  } else {
    // status=ok but not is_live (e.g. 60-120s window) — yellow as a hint
    variant = 'yellow'
    label = `Sync delayed · ${relativeTime(seconds_since)}`
  }

  const dotColor = {
    green:  'bg-emerald-500',
    yellow: 'bg-amber-500',
    red:    'bg-red-500',
    grey:   'bg-zinc-400',
  }[variant]

  const bgColor = {
    green:  'bg-emerald-50 text-emerald-700 ring-emerald-200',
    yellow: 'bg-amber-50  text-amber-800   ring-amber-200',
    red:    'bg-red-50    text-red-700     ring-red-200',
    grey:   'bg-zinc-100  text-zinc-600    ring-zinc-200',
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
