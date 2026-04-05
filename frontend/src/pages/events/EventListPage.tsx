import { useNavigate } from 'react-router-dom'
import { MOCK_EVENTS } from '@/lib/mockData'
import type { Event } from '@/lib/mockData'

// ─── Local extension — completed past event ───────────────────────────────────

const COMPLETED_EVENT: Event = {
  id: 4,
  name: 'Spring Festival 2025',
  date: '2025-04-12',
  status: 'completed',
  expected_guest_count: 280,
  bars_count: 3,
  location: 'Garden Terrace',
  created_at: '2025-01-10',
}

const ALL_EVENTS: Event[] = [...MOCK_EVENTS, COMPLETED_EVENT]

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
            {ALL_EVENTS.map((event) => {
              const isPast = event.status === 'completed'
              const textCls = isPast ? 'text-[#A0AEC0]' : 'text-[#4A5568]'

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
                    <StatusBadge status={event.status} />
                  </td>
                  <td className={`px-5 py-4 text-right tabular-nums ${textCls}`}>
                    {event.expected_guest_count.toLocaleString()}
                  </td>
                  <td className={`px-5 py-4 text-right tabular-nums ${textCls}`}>
                    {event.bars_count}
                  </td>
                  <td className={`px-5 py-4 ${textCls}`}>{event.location}</td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2 justify-end">
                      {/* View — always shown */}
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

                      {/* Edit — hidden for completed events */}
                      {!isPast && (
                        <button
                          onClick={() => navigate('/events/create')}
                          className="text-xs font-semibold text-[#4A5568] border border-[#E2E8F0] px-3 py-1.5 rounded-lg hover:bg-[#F7FAFC] transition-colors"
                        >
                          Edit
                        </button>
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
