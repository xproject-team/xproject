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
import { EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

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
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

interface WristbandActivityFeedProps {
  eventId: string | null | undefined
  limit?: number
}

export function WristbandActivityFeed({ eventId, limit = 25 }: WristbandActivityFeedProps) {
  const { data, isLoading, isError } = useWristbandActivity(eventId, limit)

  return (
    <div className="v-card">
      <div className="flex items-center justify-between px-4 py-2.5" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
            Wristband Activity
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--v-green)' }}>
            <span className="h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: 'var(--v-green)' }} />
            live
          </span>
        </div>
        <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
          {data ? `${data.total} sales` : '—'}
        </span>
      </div>

      <div className="max-h-96 overflow-y-auto">
        {isLoading && (
          <div className="space-y-2 p-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-4 animate-pulse rounded" style={{ background: 'var(--v-surface-raised)' }} />
            ))}
          </div>
        )}
        {isError && (
          <div className="p-4 text-sm" style={{ color: 'var(--v-pink)' }}>
            Could not load wristband activity. Check the backend logs.
          </div>
        )}
        {data && data.rows.length === 0 && (
          <div className="p-4">
            <EmptyState headline="No wristband sales yet" body="Sales will appear here as wristband payments come in." />
          </div>
        )}
        {data && data.rows.length > 0 && (
          <ul>
            {data.rows.map((r) => (
              <li
                key={r.transaction_id}
                className="flex items-center justify-between px-4 py-2"
                style={{ borderBottom: '0.5px solid var(--v-border)' }}
              >
                <div className="flex flex-col">
                  <span className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
                    {r.product_name}
                  </span>
                  <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
                    {r.bar_name.trim()} · {timeAgo(r.created_at)}
                  </span>
                </div>
                <span className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
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
