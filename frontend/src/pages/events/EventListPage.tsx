import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MOCK_EVENTS } from '@/lib/mockData'
import type { Event } from '@/lib/mockData'

// ─── Local extension — completed past event (mock only; remove when backend wired) ───
// NOTE: ended_at is included so getEffectiveStatus() works identically on mock + real data.

const COMPLETED_EVENT: Event = {
  id: 'evt-4',
  name: 'Spring Festival 2025',
  date: '2025-04-12',
  status: 'completed',
  expected_guest_count: 280,
  bars_count: 3,
  location: 'Garden Terrace',
  created_at: '2025-01-10',
  ended_at: '2025-04-12T23:00:00Z',
}

// ─── DATA SOURCE ──────────────────────────────────────────────────────────────
// TODO(backend): replace this with `const { data: ALL_EVENTS = [] } = useEvents()`
// when /api/v1/events is wired. Render code below is data-source-agnostic.

const ALL_EVENTS: Event[] = [...MOCK_EVENTS, COMPLETED_EVENT]

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

const STATUS_CFG: Record<Event['status'], { label: string; cls: string }> = {
  live:      { label: 'Live',      cls: 'bg-green-100 text-[#38A169] border border-green-200' },
  draft:     { label: 'Draft',     cls: 'bg-gray-100 text-[#718096] border border-gray-200' },
  active:    { label: 'Active',    cls: 'bg-blue-100 text-[#3498DB] border border-blue-200' },
  completed: { label: 'Completed', cls: 'bg-[#F7FAFC] text-[#4A5568] border border-[#E2E8F0]' },
}

function StatusBadge({ status }: { status: Event['status'] }) {
  const cfg = STATUS_CFG[status]
  return (
    <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full ${cfg.cls}`}>
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

  // Compute effective status once per event, then filter by active tab.
  const decoratedEvents = useMemo(
    () => ALL_EVENTS.map((e) => ({ ...e, _effectiveStatus: getEffectiveStatus(e) })),
    []
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
          <h1 className="text-2xl font-bold text-[#1A202C]">Events</h1>
          <p className="text-sm text-[#4A5568] mt-1">Manage and track all hospitality events</p>
        </div>
        <button
          onClick={() => navigate('/events/create')}
          className="flex items-center gap-1.5 text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
          style={{ backgroundColor: '#1ABC9C' }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#17a589')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#1ABC9C')}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Create Event
        </button>
      </div>

      {/* Status Tabs */}
      <div className="flex items-center gap-1 mb-4 border-b border-[#E2E8F0]">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={[
                'flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px',
                isActive
                  ? 'text-[#1E5A8D] border-[#1E5A8D]'
                  : 'text-[#718096] border-transparent hover:text-[#4A5568] hover:border-[#CBD5E0]',
              ].join(' ')}
            >
              {tab.label}
              <span
                className={[
                  'text-[10px] font-bold px-1.5 py-0.5 rounded-full tabular-nums',
                  isActive ? 'bg-[#EBF5FB] text-[#1E5A8D]' : 'bg-[#F7FAFC] text-[#718096]',
                ].join(' ')}
              >
                {counts[tab.key]}
              </span>
            </button>
          )
        })}
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-[#F7FAFC] border-b border-[#E2E8F0]">
              <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Event Name</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Date</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Status</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Guests</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Bars</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Venue</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Actions</th>
            </tr>
          </thead>
          <tbody>
            {visibleEvents.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-sm text-[#A0AEC0]">
                  No events in this view.
                </td>
              </tr>
            )}
            {visibleEvents.map((event) => {
              const effective = event._effectiveStatus
              const isPast    = effective === 'completed'
              const textCls   = isPast ? 'text-[#A0AEC0]' : 'text-[#4A5568]'

              return (
                <tr
                  key={event.id}
                  className={[
                    'border-b border-[#E2E8F0] last:border-0 transition-colors',
                    isPast ? 'bg-[#FAFAFA] hover:bg-[#F7FAFC]' : 'hover:bg-[#F7FAFC]',
                  ].join(' ')}
                >
                  <td className="px-5 py-4">
                    <span className={`font-semibold ${isPast ? 'text-[#A0AEC0]' : 'text-[#1A202C]'}`}>
                      {event.name}
                    </span>
                  </td>
                  <td className={`px-5 py-4 ${textCls}`}>{formatDate(event.date)}</td>
                  <td className="px-5 py-4">
                    <StatusBadge status={effective} />
                  </td>
                  <td className={`px-5 py-4 text-right tabular-nums ${textCls}`}>
                    {event.expected_guest_count.toLocaleString()}
                  </td>
                  <td className={`px-5 py-4 text-right tabular-nums ${textCls}`}>
                    {event.bars_count}
                  </td>
                  <td className={`px-5 py-4 ${textCls}`}>{event.location}</td>
                  <td className="px-5 py-4">
                    <div className="flex items-center justify-end">
                      {/* View only — all edit/end/dashboard actions live in Detail page (standard pattern) */}
                      <button
                        onClick={() => navigate(`/events/${event.id}`)}
                        className={[
                          'text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors',
                          isPast
                            ? 'text-[#718096] border-[#E2E8F0] hover:bg-[#F7FAFC]'
                            : 'text-[#1E5A8D] border-[#1E5A8D] hover:bg-[#EBF5FB]',
                        ].join(' ')}
                      >
                        View
                      </button>
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
