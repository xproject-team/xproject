import { useNavigate, useParams } from 'react-router-dom'
import { MOCK_EVENTS, MOCK_BARS, MOCK_PRODUCTS } from '@/lib/mockData'
import type { Event } from '@/lib/mockData'

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
    <span className={`text-xs font-bold px-3 py-1 rounded-full ${cfg.cls}`}>{cfg.label}</span>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'long', year: 'numeric',
  })
}

function StatCard({ icon, label, value, sub }: {
  icon: React.ReactNode
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm flex items-start gap-4">
      <div className="w-10 h-10 rounded-lg bg-[#F7FAFC] border border-[#E2E8F0] flex items-center justify-center shrink-0 text-[#1E5A8D]">
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">{label}</p>
        <p className="text-2xl font-bold text-[#1A202C] leading-none">{value}</p>
        {sub && <p className="text-xs text-[#4A5568] mt-1">{sub}</p>}
      </div>
    </div>
  )
}

// ─── Icons ────────────────────────────────────────────────────────────────────

const Icons = {
  bars: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
      <polyline strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} points="9,22 9,12 15,12 15,22" />
    </svg>
  ),
  guests: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  products: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
    </svg>
  ),
  venue: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EventDetailPage() {
  const { id }   = useParams<{ id: string }>()
  const navigate = useNavigate()

  const event = MOCK_EVENTS.find((e) => e.id === id) ?? MOCK_EVENTS[0]

  // For live events, pull live bar + product data; otherwise use event fields
  const isLive    = event.status === 'live'
  const barsCount = isLive ? MOCK_BARS.length : event.bars_count
  const products  = isLive ? MOCK_PRODUCTS : []

  const canStart = event.status === 'draft' || event.status === 'active'
  const canEnd   = event.status === 'live'

  return (
    <div className="p-6 max-w-5xl mx-auto">

      {/* Header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <button
              onClick={() => navigate('/events')}
              className="text-xs text-[#4A5568] hover:text-[#1A202C] flex items-center gap-1 transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              Events
            </button>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-[#1A202C]">{event.name}</h1>
            <StatusBadge status={event.status} />
          </div>
          <p className="text-sm text-[#4A5568] mt-1">
            {formatDate(event.date)} · {event.location}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => navigate('/events/create')}
            className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors"
          >
            Edit Event
          </button>
          {isLive && (
            <button
              onClick={() => navigate('/dashboard')}
              className="text-sm font-semibold text-white bg-[#1E5A8D] hover:bg-[#174a78] px-4 py-2 rounded-lg transition-colors"
            >
              View Dashboard
            </button>
          )}
          {canStart && (
            <button
              className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
              style={{ backgroundColor: '#38A169' }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2f8a59')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#38A169')}
            >
              Start Event
            </button>
          )}
          {canEnd && (
            <button
              className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
              style={{ backgroundColor: '#E53E3E' }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#c53030')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#E53E3E')}
            >
              End Event
            </button>
          )}
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <StatCard
          icon={Icons.bars}
          label="Bars"
          value={barsCount}
          sub="configured"
        />
        <StatCard
          icon={Icons.guests}
          label="Expected Guests"
          value={event.expected_guest_count.toLocaleString()}
          sub="registered"
        />
        <StatCard
          icon={Icons.products}
          label="Products"
          value={isLive ? products.length : '—'}
          sub="configured"
        />
        <StatCard
          icon={Icons.venue}
          label="Venue"
          value={event.location}
        />
      </div>

      {/* Event Info Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden mb-6">
        <div className="bg-[#F7FAFC] border-b border-[#E2E8F0] px-5 py-3">
          <h2 className="text-xs font-bold text-[#4A5568] uppercase tracking-widest">Event Details</h2>
        </div>
        <div className="px-5 py-5 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Event Name</p>
            <p className="text-[#1A202C] font-medium">{event.name}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Date</p>
            <p className="text-[#1A202C] font-medium">{formatDate(event.date)}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Venue</p>
            <p className="text-[#1A202C] font-medium">{event.location}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Status</p>
            <StatusBadge status={event.status} />
          </div>
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Expected Guests</p>
            <p className="text-[#1A202C] font-medium">{event.expected_guest_count.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Created</p>
            <p className="text-[#1A202C] font-medium">{formatDate(event.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Bar list (live event only) */}
      {isLive && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-[#F7FAFC] border-b border-[#E2E8F0] px-5 py-3 flex items-center justify-between">
            <h2 className="text-xs font-bold text-[#4A5568] uppercase tracking-widest">Bars</h2>
            <span className="text-xs text-[#4A5568]">{MOCK_BARS.length} bars</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#E2E8F0]">
                <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Name</th>
                <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Status</th>
                <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Staff</th>
                <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Stock</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_BARS.map((bar) => {
                const stockPct = Math.round((bar.current_stock / bar.initial_stock) * 100)
                const dotCls =
                  bar.status === 'healthy'  ? 'bg-[#38A169]' :
                  bar.status === 'warning'  ? 'bg-[#D69E2E]' :
                  'bg-[#E53E3E] animate-pulse'
                return (
                  <tr key={bar.id} className="border-b border-[#E2E8F0] last:border-0 hover:bg-[#F7FAFC] transition-colors">
                    <td className="px-5 py-3 font-medium text-[#1A202C]">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full shrink-0 ${dotCls}`} />
                        {bar.name}
                      </div>
                    </td>
                    <td className="px-5 py-3 text-[#4A5568] capitalize">{bar.status}</td>
                    <td className="px-5 py-3 text-right text-[#4A5568]">{bar.staff_count}</td>
                    <td className="px-5 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${stockPct > 60 ? 'bg-[#38A169]' : stockPct > 30 ? 'bg-[#D69E2E]' : 'bg-[#E53E3E]'}`}
                            style={{ width: `${stockPct}%` }}
                          />
                        </div>
                        <span className="text-xs text-[#4A5568] tabular-nums w-8 text-right">{stockPct}%</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

    </div>
  )
}
