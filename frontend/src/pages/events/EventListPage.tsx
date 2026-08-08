import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useEvents } from '@/features/events/hooks'
import type { Event } from '@/lib/mockData'
import { Button, EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

// ─── DATA SOURCE ──────────────────────────────────────────────────────────────
// Events are fetched via useEvents() hook (TanStack Query → /api/v1/events).
// The hook auto-refetches after any mutation (create/activate/start/end) in
// other pages — no manual reload needed. See features/events/hooks.ts.

// ─── Effective status (auto Live → Completed by ended_at) ─────────────────────
// Pure function. Works on any Event shape. Backend will eventually compute this
// server-side and we can remove it — but having it client-side is safe.

function getEffectiveStatus(event: Event): Event['status'] {
  if (event.status === 'live' && event.ended_at) {
    const ended = new Date(event.ended_at).getTime()
    if (Number.isFinite(ended) && ended < Date.now()) return 'completed'
  }
  return event.status
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────

type TabKey = 'all' | 'draft' | 'active' | 'live' | 'completed'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'all',       label: 'All'       },
  { key: 'draft',     label: 'Draft'     },
  { key: 'active',    label: 'Active'    },
  { key: 'live',      label: 'Live'      },
  { key: 'completed', label: 'Completed' },
]

// ─── Status badge ─────────────────────────────────────────────────────────────
// Semantic tint per status: live = green (+ pulsing dot), draft = dim
// neutral, active = cyan, completed = violet tint.

const STATUS_CFG: Record<Event['status'], { label: string; bg: string; color: string; pulse?: boolean }> = {
  live:      { label: 'Live',      bg: 'rgba(61, 255, 163, 0.12)',  color: 'var(--v-green)',    pulse: true },
  draft:     { label: 'Draft',     bg: 'rgba(107, 114, 128, 0.15)', color: 'var(--v-text-dim)' },
  active:    { label: 'Active',    bg: 'rgba(0, 229, 212, 0.12)',   color: 'var(--v-cyan)' },
  completed: { label: 'Completed', bg: 'rgba(177, 75, 255, 0.12)',  color: 'var(--v-violet)' },
}

function StatusBadge({ status }: { status: Event['status'] }) {
  const cfg = STATUS_CFG[status]
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full"
      style={{ background: cfg.bg, color: cfg.color }}
    >
      {cfg.pulse && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: cfg.color }} />}
      {cfg.label}
    </span>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EventListPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<TabKey>('all')

  // Fetch events from backend (hierarchical cache key ['events']).
  // isLoading is true on first fetch; isError true on network/auth failure.
  const { data: events = [], isLoading, isError, error } = useEvents()

  // Compute effective status once per event, then filter by active tab.
  const decoratedEvents = useMemo(
    () => events.map((e) => ({ ...e, _effectiveStatus: getEffectiveStatus(e) })),
    [events]
  )

  const visibleEvents = useMemo(
    () =>
      activeTab === 'all'
        ? decoratedEvents
        : decoratedEvents.filter((e) => e._effectiveStatus === activeTab),
    [activeTab, decoratedEvents]
  )

  // Per-tab count badges (always reflect totals, not filtered view).
  const counts = useMemo(() => {
    const c: Record<TabKey, number> = { all: decoratedEvents.length, draft: 0, active: 0, live: 0, completed: 0 }
    decoratedEvents.forEach((e) => { c[e._effectiveStatus] += 1 })
    return c
  }, [decoratedEvents])

  return (
    <div className="p-6 max-w-6xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium" style={{ color: 'var(--v-text)' }}>Events</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>Manage and track all hospitality events</p>
        </div>
        <Button variant="primary" onClick={() => navigate('/events/create')}>
          <span className="flex items-center gap-1.5">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Create Event
          </span>
        </Button>
      </div>

      {/* Status Tabs */}
      <div className="flex items-center gap-1 mb-4" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px"
              style={{
                color: isActive ? 'var(--v-cyan)' : 'var(--v-text-muted)',
                borderColor: isActive ? 'var(--v-cyan)' : 'transparent',
              }}
            >
              {tab.label}
              <span
                className="text-[10px] font-bold px-1.5 py-0.5 rounded-full tabular-nums"
                style={
                  isActive
                    ? { background: 'rgba(0, 229, 212, 0.12)', color: 'var(--v-cyan)' }
                    : { background: 'var(--v-surface-raised)', color: 'var(--v-text-dim)' }
                }
              >
                {counts[tab.key]}
              </span>
            </button>
          )
        })}
      </div>

      {/* Table */}
      <div className="overflow-hidden" style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Event Name</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Date</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Status</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Guests</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Bars</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Venue</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {/* Loading state — skeleton row */}
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
                  <div className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                    Loading events…
                  </div>
                </td>
              </tr>
            )}

            {/* Error state — pink banner */}
            {isError && !isLoading && (
              <tr>
                <td colSpan={7} className="px-5 py-8 text-center">
                  <div className="inline-flex items-start gap-2 text-sm" style={{ color: 'var(--v-pink)' }}>
                    <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>
                      Failed to load events.
                      {error instanceof Error && <span className="block text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>{error.message}</span>}
                    </span>
                  </div>
                </td>
              </tr>
            )}

            {/* Empty state — only when not loading and not errored */}
            {!isLoading && !isError && visibleEvents.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-12">
                  <EmptyState headline="No events in this view" body="Try a different filter, or create a new event." />
                </td>
              </tr>
            )}
            {visibleEvents.map((event) => {
              const effective = event._effectiveStatus
              const isPast    = effective === 'completed'
              const textColor = isPast ? 'var(--v-text-muted)' : 'var(--v-text)'

              return (
                <tr
                  key={event.id}
                  className="transition-colors last:border-0"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-5 py-4">
                    <span className="font-medium" style={{ color: textColor }}>
                      {event.name}
                    </span>
                  </td>
                  <td className="px-5 py-4" style={{ color: isPast ? 'var(--v-text-muted)' : 'var(--v-text)' }}>{formatDate(event.scheduled_at)}</td>
                  <td className="px-5 py-4">
                    <StatusBadge status={effective} />
                  </td>
                  <td className="px-5 py-4 text-right tabular-nums" style={{ color: textColor }}>
                    {(event.expected_guest_count ?? 0).toLocaleString()}
                  </td>
                  <td className="px-5 py-4 text-right tabular-nums" style={{ color: textColor }}>
                    {event.bars_count}
                  </td>
                  <td className="px-5 py-4" style={{ color: 'var(--v-text-muted)' }}>{event.venue.name}</td>
                  <td className="px-5 py-4">
                    <div className="flex items-center justify-end gap-2">
                      {/* View only — all edit/end/dashboard actions live in Detail page (standard pattern) */}
                      <Button variant="secondary" onClick={() => navigate(`/events/${event.id}`)}>
                        View
                      </Button>
                      {/* Chunk 3b — pre-event warehouse dispatch. Hidden once
                          the event is completed; there's nothing left to charge. */}
                      {!isPast && (
                        <Button variant="ghost" onClick={() => navigate(`/events/${event.id}/charge-bars`)}>
                          Charge Bars
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

    </div>
  )
}
