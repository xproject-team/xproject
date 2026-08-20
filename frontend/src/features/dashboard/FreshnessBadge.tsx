/**
 * Slesh polling freshness badge — Live indicator only.
 *
 * Simplified per Day 3 restyle (Vera Event design system): shows a single
 * green "Live" pill when the event is live AND has Slesh-mapped bars;
 * renders nothing otherwise (draft, scheduled, completed, or no Slesh
 * integration on this event) — no "stalled", no hours-ago text. The
 * precise polling interval is still available as a hover tooltip rather
 * than baked into the label.
 */
import { useFreshness } from './useFreshness'
import '@/design-system/components/components.css'

export interface FreshnessBadgeProps {
  /**
   * Whether the current event has any Slesh-mapped bars. The badge
   * monitors the Slesh poller — for events with no Slesh integration
   * (manual_bartender flows, simulators, dry runs) the poll state is
   * irrelevant and misleading. Hide the badge in those cases.
   */
  eventHasSleshBars: boolean
  /** True only while the event's status is 'live'. Draft/scheduled/completed
   *  events never show a polling indicator — there's nothing live to poll. */
  isLive: boolean
  /** Which event's polling state to show — GET /events/{eventId}/polling-health. */
  eventId: string | null | undefined
}

export function FreshnessBadge({ eventHasSleshBars, isLive, eventId }: FreshnessBadgeProps) {
  const { data } = useFreshness(eventId)

  if (!eventHasSleshBars || !isLive) return null

  const tooltip = data?.seconds_since_last_run != null
    ? `polled ${data.seconds_since_last_run.toFixed(4)}s ago`
    : undefined

  return (
    <span className="v-badge v-badge--success inline-flex items-center gap-1.5" title={tooltip}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: 'var(--v-green)' }} />
      Live
    </span>
  )
}
