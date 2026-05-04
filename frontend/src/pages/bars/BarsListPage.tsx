import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useBars } from '@/features/bars/hooks'
import { useEvents } from '@/features/events/hooks'
import type { BarRow } from '@/lib/mockData'

// ─── DATA SOURCE ──────────────────────────────────────────────────────────────
// Bars are fetched via useBars() — TanStack Query → /api/v1/bars.
// Optionally filtered by event_id when the user picks an event in the
// dropdown. The hook auto-refetches after any create/update/delete mutation.

// ─── Active/Inactive filter tabs ──────────────────────────────────────────────

type FilterKey = 'all' | 'active' | 'inactive'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all',      label: 'All'      },
  { key: 'active',   label: 'Active'   },
  { key: 'inactive', label: 'Inactive' },
]

// ─── Status pill ──────────────────────────────────────────────────────────────

const ACTIVE_CFG  = { label: 'Active',   cls: 'bg-green-100 text-[#38A169] border border-green-200' }
const INACTIVE_CFG = { label: 'Inactive', cls: 'bg-gray-100 text-[#718096] border border-gray-200' }

function StatusPill({ isActive }: { isActive: boolean }) {
  const cfg = isActive ? ACTIVE_CFG : INACTIVE_CFG
  return (
    <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

const TYPE_CFG: Record<string, { label: string; cls: string }> = {
  drinks: { label: 'Drinks', cls: 'bg-sky-50    text-sky-800    border border-sky-200'    },
  food:   { label: 'Food',   cls: 'bg-amber-50  text-amber-800  border border-amber-200'  },
  mixed:  { label: 'Mixed',  cls: 'bg-purple-50 text-purple-800 border border-purple-200' },
}

function TypeBadge({ type }: { type: string }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG.drinks
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BarsListPage() {
  const navigate = useNavigate()

  const [eventId,    setEventId]    = useState<string>('')   // '' = all events
  const [activeTab,  setActiveTab]  = useState<FilterKey>('all')

  const { data: events = [] } = useEvents()
  const { data: bars = [], isLoading, isError, error } = useBars(eventId || undefined)

  // Map of event id -> name for quick lookup in the table
  const eventNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const e of events) m.set(e.id, e.name)
    return m
  }, [events])

  const visibleBars = useMemo<BarRow[]>(() => {
    if (activeTab === 'active')   return bars.filter((b) => b.is_active)
    if (activeTab === 'inactive') return bars.filter((b) => !b.is_active)
    return bars
  }, [activeTab, bars])

  const counts = useMemo(() => ({
    all:      bars.length,
    active:   bars.filter((b) => b.is_active).length,
    inactive: bars.filter((b) => !b.is_active).length,
  }), [bars])

  return (
    <div className="flex flex-col h-full bg-white">
      {/* ─── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <h1 className="text-xl font-bold text-[#1A202C]">Bars</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            {counts.all} total · {counts.active} active · {counts.inactive} inactive
          </p>
        </div>
        <button
          onClick={() => navigate('/bars/new')}
          className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors"
        >
          + Create Bar
        </button>
      </div>

      {/* ─── Filters row ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 border-b border-[#E2E8F0] px-6 py-3">
        {/* Event filter dropdown */}
        <label className="flex items-center gap-2 text-xs text-[#4A5568]">
          Event:
          <select
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
            className="border border-[#E2E8F0] rounded px-2 py-1 text-xs bg-white"
          >
            <option value="">All events</option>
            {events.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </label>

        {/* Status tabs */}
        <div className="flex gap-1 ml-4">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setActiveTab(f.key)}
              className={[
                'text-xs font-medium px-3 py-1 rounded-full transition-colors',
                activeTab === f.key
                  ? 'bg-[#1E5A8D] text-white'
                  : 'text-[#4A5568] hover:bg-[#F7FAFC]',
              ].join(' ')}
            >
              {f.label} <span className="opacity-75">({counts[f.key]})</span>
            </button>
          ))}
        </div>
      </div>

      {/* ─── Body ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading && (
          <div className="text-center text-sm text-[#718096] py-12">Loading bars…</div>
        )}

        {isError && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
            Failed to load bars: {(error as Error)?.message ?? 'unknown error'}
          </div>
        )}

        {!isLoading && !isError && visibleBars.length === 0 && (
          <div className="text-center text-sm text-[#718096] py-12">
            {bars.length === 0
              ? 'No bars yet. Click "+ Create Bar" to add one.'
              : `No ${activeTab} bars.`}
          </div>
        )}

        {!isLoading && !isError && visibleBars.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-semibold uppercase text-[#4A5568] border-b border-[#E2E8F0]">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Event</th>
                <th className="py-2 pr-4">Slesh ID</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {visibleBars.map((bar) => (
                <tr key={bar.id} className="border-b border-[#F7FAFC] hover:bg-[#F7FAFC]">
                  <td className="py-3 pr-4 font-medium text-[#1A202C]">{bar.name}</td>
                  <td className="py-3 pr-4"><TypeBadge type={bar.bar_type} /></td>
                  <td className="py-3 pr-4 text-[#4A5568] text-xs">
                    {eventNameById.get(bar.event_id) ?? '(unknown)'}
                  </td>
                  <td className="py-3 pr-4 text-[#718096] text-xs font-mono">
                    {bar.slesh_negozio_id ? bar.slesh_negozio_id.slice(0, 12) + '…' : '—'}
                  </td>
                  <td className="py-3 pr-4"><StatusPill isActive={bar.is_active} /></td>
                  <td className="py-3 pr-4">
                    <button
                      onClick={() => navigate(`/bars/${bar.id}`)}
                      className="text-xs font-medium text-[#1E5A8D] hover:underline"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
