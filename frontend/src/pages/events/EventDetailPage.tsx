import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { MOCK_PRODUCTS } from '@/lib/mockData'
import { useBars } from '@/features/bars/hooks'
import type { Event } from '@/lib/mockData'
import {
  useEvent,
  useUpdateEvent,
  useActivateEvent,
  useStartEvent,
  useEndEvent,
  getApiError,
} from '@/features/events/hooks'
import { useVenues } from '@/features/venues/hooks'
import { usePermissions } from '@/features/auth/usePermissions'

// Convert ISO datetime string (with timezone) to the format
// expected by <input type="datetime-local">. The input doesn't
// accept timezone suffixes — strip everything from the 'Z' or
// '+' onward, and trim seconds.
function toDatetimeLocal(iso: string | undefined | null): string {
  if (!iso) return ''
  // "2026-06-19T19:00:00+02:00" -> "2026-06-19T19:00"
  return iso.replace(/(:\d\d)?([Z+-].*)?$/, '').slice(0, 16)
}


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

// ─── FieldDisplay (inline edit: plain text or locked with icon) ───────────────

function FieldDisplay({ locked, children }: { locked: boolean; children: React.ReactNode }) {
  if (!locked) {
    return <p className="text-[#1A202C] font-medium">{children}</p>
  }
  return (
    <div className="relative group inline-flex items-center gap-1.5 text-[#A0AEC0] font-medium" title="Locked while event is live">
      <span>{children}</span>
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
      </svg>
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

/**
 * EventDetailContent — renders the page body when an `event` is available.
 * Lifted from EventDetailPage so that hooks that depend on `event` can use it
 * without TypeScript complaints about `event` being possibly undefined.
 */
function EventDetailContent({ event }: { event: Event }) {
  const navigate = useNavigate()
  // Backend event is the single source of truth — no local override layer.
  const effective = event

  // ─── Status-driven flags ────────────────────────────────────────────────────
  const permissions               = usePermissions()
  const effectiveCanEdit          = effective.status !== 'completed'
  const effectiveCanStart         = effective.status === 'draft' || effective.status === 'active'
  const effectiveCanEnd           = effective.status === 'live'
  const effectiveCanViewDashboard = effective.status === 'active' || effective.status === 'live'
  const effectiveCanViewReport    = effective.status === 'completed'
  const effectiveIsLive           = effective.status === 'live'
  // Real bars data — replaces MOCK_BARS for count and table
  const barsQuery   = useBars(effective.id)
  const realBars    = barsQuery.data ?? []
  const realBarsCount = realBars.length
  // Reconciliation is available once the event has gone LIVE at least once
  // (i.e., status is 'live' or 'completed') AND the user has Owner permission.
  const effectiveCanViewReconciliation =
    permissions.canGenerateReport &&
    (effective.status === 'live' || effective.status === 'completed')
  const products  = effectiveIsLive ? MOCK_PRODUCTS : []

  // ─── Inline edit draft ──────────────────────────────────────────────────────
  type Draft = {
    name: string
    expected_guest_count: number
    scheduled_at: string
    scheduled_end_at: string
    venue_id: string
    bars_count: number
  }
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState<Draft>({
    name: effective.name,
    expected_guest_count: effective.expected_guest_count ?? 0,
    scheduled_at: effective.scheduled_at,
    scheduled_end_at: effective.scheduled_end_at,
    venue_id: effective.venue.id,
    bars_count: effective.bars_count,
  })

  // ─── Lock matrix ────────────────────────────────────────────────────────────
  const isLiveEdit = effective.status === 'live'
  const lockMatrix = {
    name:      false,
    guests:    false,
    date:      isLiveEdit,
    venue:     isLiveEdit,
    barsCount: isLiveEdit,
  }

  // ─── Dialog states ──────────────────────────────────────────────────────────
  const [showEndConfirm, setShowEndConfirm]             = useState(false)
  const [showGoLiveConfirm, setShowGoLiveConfirm]       = useState(false)
  const [showGoLiveDestination, setShowGoLiveDestination] = useState(false)

  // ─── Mutations (TanStack Query) ─────────────────────────────────────────────
  const updateMutation   = useUpdateEvent()
  const activateMutation = useActivateEvent()
  const startMutation    = useStartEvent()
  const endMutation      = useEndEvent()

  // Venues dropdown data
  const { data: venues = [] } = useVenues()

  // Toast state for non-blocking errors (e.g. field_locked)
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  function showToast(message: string) {
    setToastMessage(message)
    setTimeout(() => setToastMessage(null), 5000)
  }

  // ─── Handlers ───────────────────────────────────────────────────────────────
  function handleSave() {
    if (!draft.name.trim()) { alert('Event name cannot be empty.'); return }
    if (draft.expected_guest_count < 0) { alert('Expected guests cannot be negative.'); return }

    updateMutation.mutate(
      {
        id: event.id,
        payload: {
          name: draft.name,
          venue_id: draft.venue_id,
          scheduled_at: draft.scheduled_at,
          scheduled_end_at: draft.scheduled_end_at,
          expected_guest_count: draft.expected_guest_count,
          version: event.version,
        },
      },
      {
        onSuccess: () => setIsEditing(false),
        onError: (err) => {
          const api = getApiError(err)
          if (api?.error === 'field_locked') {
            showToast(api.message)
          } else if (api?.error === 'stale_version') {
            alert('This event was modified by someone else. Refreshing to show the latest version.')
            setIsEditing(false)
          } else {
            alert(api?.message ?? 'Failed to save event.')
          }
        },
      },
    )
  }

  function handleCancel() {
    setDraft({
      name: effective.name,
      expected_guest_count: effective.expected_guest_count ?? 0,
      scheduled_at: effective.scheduled_at,
      scheduled_end_at: effective.scheduled_end_at,
      venue_id: effective.venue.id,
      bars_count: effective.bars_count,
    })
    setIsEditing(false)
  }

  function handleActivate() {
    activateMutation.mutate(event.id, {
      onError: (err) => {
        const api = getApiError(err)
        alert(api?.message ?? 'Failed to activate event.')
      },
    })
  }

  function handleGoLive() {
    setShowGoLiveConfirm(true)
  }

  function handleGoLiveConfirmed() {
    setShowGoLiveConfirm(false)
    startMutation.mutate(event.id, {
      onSuccess: () => setShowGoLiveDestination(true),
      onError: (err) => {
        const api = getApiError(err)
        if (api && api.error === 'event_already_live') {
          // Type assertion — TS discriminated-union narrowing fails here because
          // the fallback variant '{ error: string }' is a superset of the literal.
          const conflict = api as Extract<typeof api, { error: 'event_already_live' }>
          alert(
            `${conflict.message}\n\n` +
            `Go to "${conflict.conflicting_event.name}" and end it first, then try again.`
          )
        } else {
          alert(api?.message ?? 'Failed to start event.')
        }
      },
    })
  }

  function handleGoToDashboard() {
    setShowGoLiveDestination(false)
    navigate('/dashboard')
  }

  function handleEndConfirmed() {
    setShowEndConfirm(false)
    endMutation.mutate(event.id, {
      onError: (err) => {
        const api = getApiError(err)
        alert(api?.message ?? 'Failed to end event.')
      },
    })
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Toast — bottom-right, auto-dismisses after 5s */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#1A202C] text-white text-sm px-4 py-3 rounded-lg shadow-lg max-w-sm">
          {toastMessage}
        </div>
      )}

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
            <h1 className="text-2xl font-bold text-[#1A202C]">{effective.name}</h1>
            <StatusBadge status={effective.status} />
          </div>
          <p className="text-sm text-[#4A5568] mt-1">
            {formatDate(effective.scheduled_at)} · {effective.venue.name}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Reconciliation report — Owner only, after event has gone LIVE */}
          {effectiveCanViewReconciliation && (
            <button
              type="button"
              onClick={() => navigate(`/events/${effective.id}/reconciliation`)}
              className="text-sm font-semibold text-white bg-[#1E5A8D] hover:bg-[#164d7a] px-4 py-2 rounded-lg transition-colors"
            >
              View Reconciliation
            </button>
          )}
          {/* Edit / Save / Cancel */}
          {effectiveCanEdit && !isEditing && (
            <button
              onClick={() => effective.status === 'draft' ? navigate(`/events/${effective.id}/edit`) : setIsEditing(true)}
              className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors"
            >
              Edit Event
            </button>
          )}
          {isEditing && (
            <>
              <button
                onClick={handleCancel}
                className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
                style={{ backgroundColor: '#38A169' }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2f8a59')}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#38A169')}
              >
                Save Changes
              </button>
            </>
          )}

          {/* View Dashboard — Active + Live */}
          {effectiveCanViewDashboard && !isEditing && (
            <button
              onClick={() => navigate('/dashboard')}
              className="text-sm font-semibold text-white bg-[#1E5A8D] hover:bg-[#174a78] px-4 py-2 rounded-lg transition-colors"
            >
              View Dashboard
            </button>
          )}

          {/* View Report — Completed */}
          {effectiveCanViewReport && (
            <button
              onClick={() => navigate(`/reports/${effective.id}`)}
              className="text-sm font-semibold text-white bg-[#1E5A8D] hover:bg-[#174a78] px-4 py-2 rounded-lg transition-colors"
            >
              View Report
            </button>
          )}

          {/* Activate Event — Draft only */}
          {effectiveCanStart && effective.status === 'draft' && !isEditing && (
            <button
              onClick={handleActivate}
              className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
              style={{ backgroundColor: '#38A169' }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2f8a59')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#38A169')}
            >
              Activate Event
            </button>
          )}

          {/* Go Live — Active only */}
          {effectiveCanStart && effective.status === 'active' && !isEditing && (
            <button
              onClick={handleGoLive}
              className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
              style={{ backgroundColor: '#38A169' }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2f8a59')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#38A169')}
            >
              Go Live
            </button>
          )}

          {/* End Event — Live only */}
          {effectiveCanEnd && !isEditing && (
            <button
              onClick={() => setShowEndConfirm(true)}
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
        <StatCard icon={Icons.bars} label="Bars" value={effectiveIsLive ? realBarsCount : effective.bars_count} sub="configured" />
        <StatCard icon={Icons.guests} label="Expected Guests" value={(effective.expected_guest_count ?? 0).toLocaleString()} sub="registered" />
        <StatCard icon={Icons.products} label="Products" value={effectiveIsLive ? products.length : '\u2014'} sub="configured" />
        <StatCard icon={Icons.venue} label="Venue" value={effective.venue.name} />
      </div>

      {/* Event Info Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden mb-6">
        <div className="bg-[#F7FAFC] border-b border-[#E2E8F0] px-5 py-3">
          <h2 className="text-xs font-bold text-[#4A5568] uppercase tracking-widest">Event Details</h2>
        </div>
        <div className="px-5 py-5 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">

          {/* Event Name */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Event Name</p>
            {isEditing && !lockMatrix.name ? (
              <>
                <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  className="w-full px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30" />
                <p className="text-[10px] text-[#A0AEC0] mt-1">Was: {effective.name}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.name}>{effective.name}</FieldDisplay>
            )}
          </div>

          {/* Date */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Date</p>
            {isEditing && !lockMatrix.date ? (
              <>
                <input type="datetime-local" value={toDatetimeLocal(draft.scheduled_at)} onChange={(e) => setDraft({ ...draft, scheduled_at: e.target.value })}
                  className="w-full px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30" />
                <input type="datetime-local" value={toDatetimeLocal(draft.scheduled_end_at)} onChange={(e) => setDraft({ ...draft, scheduled_end_at: e.target.value })}
                  className="w-full mt-1 px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]" />
                <p className="text-[10px] text-[#A0AEC0] mt-1">Was: {formatDate(effective.scheduled_at)} → {formatDate(effective.scheduled_end_at)}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.date}>{formatDate(effective.scheduled_at)} → {formatDate(effective.scheduled_end_at)}</FieldDisplay>
            )}
          </div>

          {/* Venue */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Venue</p>
            {isEditing && !lockMatrix.venue ? (
              <>
                <select
                  value={draft.venue_id}
                  onChange={(e) => setDraft({ ...draft, venue_id: e.target.value })}
                  className="w-full px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 bg-white"
                >
                  {venues.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
                <p className="text-[10px] text-[#A0AEC0] mt-1">Was: {effective.venue.name}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.venue}>{effective.venue.name}</FieldDisplay>
            )}
          </div>

          {/* Bars Count */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Number of Bars</p>
            {isEditing && !lockMatrix.barsCount ? (
              <>
                <input type="number" min={1} value={draft.bars_count} onChange={(e) => setDraft({ ...draft, bars_count: Number(e.target.value) || 1 })}
                  className="w-full px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 tabular-nums" />
                <p className="text-[10px] text-[#A0AEC0] mt-1">Was: {effective.bars_count}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.barsCount}>{effective.bars_count}</FieldDisplay>
            )}
          </div>

          {/* Status */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Status</p>
            <StatusBadge status={effective.status} />
          </div>

          {/* Expected Guests */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Expected Guests</p>
            {isEditing && !lockMatrix.guests ? (
              <>
                <input type="number" min={0} value={draft.expected_guest_count} onChange={(e) => setDraft({ ...draft, expected_guest_count: Number(e.target.value) || 0 })}
                  className="w-full px-3 py-1.5 text-[#1A202C] font-medium border border-[#1E5A8D] rounded-md focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 tabular-nums" />
                <p className="text-[10px] text-[#A0AEC0] mt-1">Was: {(effective.expected_guest_count ?? 0).toLocaleString()}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.guests}>{(effective.expected_guest_count ?? 0).toLocaleString()}</FieldDisplay>
            )}
          </div>

          {/* Created */}
          <div>
            <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-0.5">Created</p>
            <p className="text-[#1A202C] font-medium">{formatDate(effective.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Bar list (live event only) */}
      {effectiveIsLive && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden">
          <div className="bg-[#F7FAFC] border-b border-[#E2E8F0] px-5 py-3 flex items-center justify-between">
            <h2 className="text-xs font-bold text-[#4A5568] uppercase tracking-widest">Bars</h2>
            <span className="text-xs text-[#4A5568]">{realBarsCount} bars</span>
          </div>
          {barsQuery.isLoading ? (
            <div className="px-5 py-8 text-center text-sm text-[#A0AEC0]">Loading bars…</div>
          ) : barsQuery.isError ? (
            <div className="px-5 py-8 text-center text-sm text-[#E53E3E]">Failed to load bars.</div>
          ) : realBars.length === 0 ? (
            <div className="px-5 py-8 text-center text-sm text-[#A0AEC0]">No bars configured for this event yet.</div>
          ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[#E2E8F0]">
                <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Name</th>
                <th className="text-left px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Type</th>
                <th className="text-right px-5 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">Status</th>
              </tr>
            </thead>
            <tbody>
              {realBars.map((bar) => (
                <tr key={bar.id} className="border-b border-[#E2E8F0] last:border-0 hover:bg-[#F7FAFC] transition-colors">
                  <td className="px-5 py-3 font-medium text-[#1A202C]">{bar.name}</td>
                  <td className="px-5 py-3 text-[#4A5568] capitalize">{bar.bar_type}</td>
                  <td className="px-5 py-3 text-right">
                    {bar.is_active ? (
                      <span className="inline-flex items-center gap-1.5 text-xs text-[#38A169]">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#38A169]" />
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-xs text-[#A0AEC0]">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#A0AEC0]" />
                        Inactive
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
        </div>
      )}

      {/* Go Live Confirmation Modal */}
      {showGoLiveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowGoLiveConfirm(false)}>
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-[#38A169]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-bold text-[#1A202C]">Go Live with {effective.name}?</h3>
                <p className="text-sm text-[#4A5568] mt-1">This opens the POS, activates dashboards, and begins live data collection. The event configuration becomes locked.</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowGoLiveConfirm(false)} className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors">Cancel</button>
              <button onClick={handleGoLiveConfirmed} className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors" style={{ backgroundColor: '#38A169' }} onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#2f8a59')} onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#38A169')}>Yes, Go Live</button>
            </div>
          </div>
        </div>
      )}

      {/* Go Live Destination Choice Modal */}
      {showGoLiveDestination && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowGoLiveDestination(false)}>
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-[#1E5A8D]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-bold text-[#1A202C]">{effective.name} is now live</h3>
                <p className="text-sm text-[#4A5568] mt-1">Where do you want to go next?</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowGoLiveDestination(false)} className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors">Stay on Detail</button>
              <button onClick={handleGoToDashboard} className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors bg-[#1E5A8D] hover:bg-[#174a78]">Open Dashboard</button>
            </div>
          </div>
        </div>
      )}

      {/* End Event Confirmation Modal */}
      {showEndConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowEndConfirm(false)}>
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-[#E53E3E]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-bold text-[#1A202C]">End {effective.name}?</h3>
                <p className="text-sm text-[#4A5568] mt-1">This will lock the event, freeze all sales data, and start generating the post-event report. This cannot be undone.</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowEndConfirm(false)} className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors">Cancel</button>
              <button onClick={handleEndConfirmed} className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors" style={{ backgroundColor: '#E53E3E' }} onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#c53030')} onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#E53E3E')}>Yes, End Event</button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}


/**
 * EventDetailPage — outer wrapper.
 * Handles the useEvent(id) fetch lifecycle (loading / error / not-found).
 * Only mounts EventDetailContent once `event` is guaranteed non-null, which
 * means EventDetailContent's hooks can treat `event` as always defined.
 */
export default function EventDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: event, isLoading, isError, error } = useEvent(id)

  if (isLoading) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="flex items-center gap-3 text-[#4A5568]">
          <div className="w-4 h-4 border-2 border-[#CBD5E0] border-t-[#1E5A8D] rounded-full animate-spin" />
          <span className="text-sm">Loading event\u2026</span>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <p className="text-sm font-semibold text-[#E53E3E]">Failed to load event.</p>
          {error instanceof Error && (
            <p className="text-xs text-[#A0AEC0] mt-1">{error.message}</p>
          )}
          <button
            onClick={() => navigate('/events')}
            className="mt-3 text-sm font-semibold text-[#1E5A8D] hover:underline"
          >
            \u2190 Back to Events
          </button>
        </div>
      </div>
    )
  }

  if (!event) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-xl p-5">
          <p className="text-sm font-semibold text-[#1A202C]">Event not found.</p>
          <p className="text-xs text-[#4A5568] mt-1">
            The event may have been deleted or you do not have access.
          </p>
          <button
            onClick={() => navigate('/events')}
            className="mt-3 text-sm font-semibold text-[#1E5A8D] hover:underline"
          >
            \u2190 Back to Events
          </button>
        </div>
      </div>
    )
  }

  return <EventDetailContent event={event} />
}
