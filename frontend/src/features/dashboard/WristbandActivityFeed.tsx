/**
 * Wristband Activity Feed.
 *
 * Renders a card with the last N token-paid transactions, newest first.
 * Auto-refreshes via the useWristbandActivity hook (every 15s).
 *
 * Visual:
 *   - Card with header "Wristband Activity · live"
 *   - Each row: time-ago · product · bar · price
 *   - Empty state: "No wristband sales yet"
 *   - Loading: dimmed skeleton lines
 */
import { useWristbandActivity } from './useWristbandActivity'

function fmtEur(cents: number | null): string {
  if (cents === null || cents === undefined) return '—'
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(cents / 100)
}

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60)    return `${seconds}s ago`
  if (seconds < 3600)  return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return new Date(iso).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

interface WristbandActivityFeedProps {
  eventId: string | null | undefined
  limit?: number
}

export function WristbandActivityFeed({ eventId, limit = 25 }: WristbandActivityFeedProps) {
  const { data, isLoading, isError } = useWristbandActivity(eventId, limit)

  return (
    <div className="rounded-lg border border-zinc-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-zinc-900">
            Wristband Activity
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            live
          </span>
        </div>
        <span className="text-xs text-zinc-500">
          {data ? `${data.total} sales` : '—'}
        </span>
      </div>

      <div className="max-h-96 overflow-y-auto">
        {isLoading && (
          <div className="space-y-2 p-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-4 animate-pulse rounded bg-zinc-100" />
            ))}
          </div>
        )}
        {isError && (
          <div className="p-4 text-sm text-red-600">
            Could not load wristband activity. Check the backend logs.
          </div>
        )}
        {data && data.rows.length === 0 && (
          <div className="p-4 text-sm text-zinc-500">
            No wristband sales yet.
          </div>
        )}
        {data && data.rows.length > 0 && (
          <ul className="divide-y divide-zinc-50">
            {data.rows.map((r) => (
              <li
                key={r.transaction_id}
                className="flex items-center justify-between px-4 py-2 hover:bg-zinc-50"
              >
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-zinc-900">
                    {r.product_name}
                  </span>
                  <span className="text-xs text-zinc-500">
                    {r.bar_name.trim()} · {timeAgo(r.created_at)}
                  </span>
                </div>
                <span className="text-sm font-semibold text-zinc-700">
                  {fmtEur(r.price_cents)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
