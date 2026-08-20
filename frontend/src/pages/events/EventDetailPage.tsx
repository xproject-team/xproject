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
import { useReportsForEvent } from '@/features/reports/useReports'
import { inputCls } from '@/design-system/wizardForm'
import { Badge, Button, EmptyState, type BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'

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
// Same semantic colors as the events list (EventListPage.tsx): live = green
// (+ pulsing dot), draft = neutral, active = cyan, completed = violet.

const STATUS_CFG: Record<Event['status'], { label: string; variant: BadgeVariant; pulse?: boolean }> = {
  live:      { label: 'Live',      variant: 'success', pulse: true },
  draft:     { label: 'Draft',     variant: 'neutral' },
  active:    { label: 'Active',    variant: 'info' },
  completed: { label: 'Completed', variant: 'violet' },
}

function StatusBadge({ status }: { status: Event['status'] }) {
  const cfg = STATUS_CFG[status]
  return (
    <Badge variant={cfg.variant}>
      <span className="inline-flex items-center gap-1.5">
        {cfg.pulse && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--v-green)' }} />}
        {cfg.label}
      </span>
    </Badge>
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
    <div className="v-card p-4 flex items-start gap-4">
      <div
        className="w-10 h-10 rounded-[var(--v-radius-sm)] flex items-center justify-center shrink-0"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-cyan)' }}
      >
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>{label}</p>
        <p className="text-2xl font-medium leading-none" style={{ color: 'var(--v-text)' }}>{value}</p>
        {sub && <p className="text-xs mt-1" style={{ color: 'var(--v-text-muted)' }}>{sub}</p>}
      </div>
    </div>
  )
}

// ─── FieldDisplay (inline edit: plain text or locked with icon) ───────────────

function FieldDisplay({ locked, children }: { locked: boolean; children: React.ReactNode }) {
  if (!locked) {
    return <p className="font-medium" style={{ color: 'var(--v-text)' }}>{children}</p>
  }
  return (
    <div className="relative group inline-flex items-center gap-1.5 font-medium" style={{ color: 'var(--v-text-dim)' }} title="Locked while event is live">
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
  const effectiveCanViewDashboard = effective.status !== 'draft'
  const effectiveCanViewReport    = effective.status === 'completed'
  const effectiveIsLive           = effective.status === 'live'
  // Real bars data — replaces MOCK_BARS for count and table
  const barsQuery   = useBars(effective.id)
  const realBars    = barsQuery.data ?? []
  const realBarsCount = realBars.length

  // "View Report" needs an actual report id, not the event id — report rows
  // are a distinct primary key (a report is generated per event, but its id
  // is its own). Bug fix: this button used to navigate(`/reports/${effective.id}`),
  // which resolved to "Report not found" for every event. Prefer the newest
  // ready 'it' report (matching the generate modal's default language), else
  // any ready report, else the newest row of any status so a still-generating
  // report at least routes somewhere sensible instead of nowhere.
  const eventReportsQuery = useReportsForEvent(effectiveCanViewReport ? effective.id : null)
  const eventReports = eventReportsQuery.data ?? []
  const reportToView =
    eventReports.find((r) => r.status === 'ready' && r.language === 'it') ??
    eventReports.find((r) => r.status === 'ready') ??
    eventReports[0] ??
    null
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
    navigate(`/dashboard?event_id=${event.id}`)
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
        <div
          className="fixed bottom-6 right-6 z-50 text-sm px-4 py-3 rounded-lg max-w-sm"
          style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}
        >
          {toastMessage}
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <button
              onClick={() => navigate('/events')}
              className="text-xs flex items-center gap-1 transition-colors"
              style={{ color: 'var(--v-text-muted)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-text)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-muted)')}
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              Events
            </button>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-medium" style={{ color: 'var(--v-text)' }}>{effective.name}</h1>
            <StatusBadge status={effective.status} />
          </div>
          <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>
            {formatDate(effective.scheduled_at)} · {effective.venue.name}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Reconciliation report — Owner only, after event has gone LIVE */}
          {effectiveCanViewReconciliation && (
            <Button variant="secondary" onClick={() => navigate(`/events/${effective.id}/reconciliation`)}>
              View Reconciliation
            </Button>
          )}
          {/* Edit / Save / Cancel */}
          {effectiveCanEdit && !isEditing && (
            <Button variant="secondary" onClick={() => effective.status === 'draft' ? navigate(`/events/${effective.id}/edit`) : setIsEditing(true)}>
              Edit Event
            </Button>
          )}
          {isEditing && (
            <>
              <Button variant="secondary" onClick={handleCancel}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleSave}>
                Save Changes
              </Button>
            </>
          )}

          {/* View Dashboard — Active + Live */}
          {effectiveCanViewDashboard && !isEditing && (
            <Button variant="primary" onClick={() => navigate(`/dashboard?event_id=${effective.id}`)}>
              View Dashboard
            </Button>
          )}

          {/* View Report — Completed */}
          {effectiveCanViewReport && (
            <Button
              variant="primary"
              onClick={() => reportToView && navigate(`/reports/${reportToView.id}`)}
              disabled={!reportToView}
              title={reportToView ? undefined : 'Report not generated yet'}
            >
              View Report
            </Button>
          )}

          {/* Activate Event — Draft only */}
          {effectiveCanStart && effective.status === 'draft' && !isEditing && (
            <Button variant="primary" onClick={handleActivate}>
              Activate Event
            </Button>
          )}

          {/* Go Live — Active only */}
          {effectiveCanStart && effective.status === 'active' && !isEditing && (
            <Button variant="primary" onClick={handleGoLive}>
              Go Live
            </Button>
          )}

          {/* End Event — Live only */}
          {effectiveCanEnd && !isEditing && (
            <button
              onClick={() => setShowEndConfirm(true)}
              className="text-sm font-semibold px-4 py-2 rounded-[var(--v-radius-sm)] transition-colors"
              style={{ color: 'var(--v-pink)', border: '0.5px solid var(--v-pink)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255, 61, 113, 0.08)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              End Event
            </button>
          )}
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard icon={Icons.bars} label="Bars" value={effectiveIsLive ? realBarsCount : effective.bars_count} sub="configured" />
        <StatCard icon={Icons.guests} label="Expected Guests" value={(effective.expected_guest_count ?? 0).toLocaleString()} sub="registered" />
        <StatCard icon={Icons.products} label="Products" value={effectiveIsLive ? products.length : '\u2014'} sub="configured" />
        <StatCard icon={Icons.venue} label="Venue" value={effective.venue.name} />
      </div>

      {/* Event Info Card */}
      <div className="v-card overflow-hidden mb-3">
        <div className="px-5 py-3" style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
          <h2 className="text-[11px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Event Details</h2>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">

          {/* Event Name */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Event Name</p>
            {isEditing && !lockMatrix.name ? (
              <>
                <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  className={inputCls} />
                <p className="text-[10px] mt-1" style={{ color: 'var(--v-text-dim)' }}>Was: {effective.name}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.name}>{effective.name}</FieldDisplay>
            )}
          </div>

          {/* Date */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Date</p>
            {isEditing && !lockMatrix.date ? (
              <>
                <input type="datetime-local" value={toDatetimeLocal(draft.scheduled_at)} onChange={(e) => setDraft({ ...draft, scheduled_at: e.target.value })}
                  className={`${inputCls} [color-scheme:dark]`} />
                <input type="datetime-local" value={toDatetimeLocal(draft.scheduled_end_at)} onChange={(e) => setDraft({ ...draft, scheduled_end_at: e.target.value })}
                  className={`${inputCls} [color-scheme:dark] mt-1`} />
                <p className="text-[10px] mt-1" style={{ color: 'var(--v-text-dim)' }}>Was: {formatDate(effective.scheduled_at)} → {formatDate(effective.scheduled_end_at)}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.date}>{formatDate(effective.scheduled_at)} → {formatDate(effective.scheduled_end_at)}</FieldDisplay>
            )}
          </div>

          {/* Venue */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Venue</p>
            {isEditing && !lockMatrix.venue ? (
              <>
                <select
                  value={draft.venue_id}
                  onChange={(e) => setDraft({ ...draft, venue_id: e.target.value })}
                  className={inputCls}
                >
                  {venues.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
                <p className="text-[10px] mt-1" style={{ color: 'var(--v-text-dim)' }}>Was: {effective.venue.name}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.venue}>{effective.venue.name}</FieldDisplay>
            )}
          </div>

          {/* Bars Count */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Number of Bars</p>
            {isEditing && !lockMatrix.barsCount ? (
              <>
                <input type="number" min={1} value={draft.bars_count} onChange={(e) => setDraft({ ...draft, bars_count: Number(e.target.value) || 1 })}
                  className={`${inputCls} tabular-nums`} />
                <p className="text-[10px] mt-1" style={{ color: 'var(--v-text-dim)' }}>Was: {effective.bars_count}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.barsCount}>{effective.bars_count}</FieldDisplay>
            )}
          </div>

          {/* Status */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Status</p>
            <StatusBadge status={effective.status} />
          </div>

          {/* Expected Guests */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Expected Guests</p>
            {isEditing && !lockMatrix.guests ? (
              <>
                <input type="number" min={0} value={draft.expected_guest_count} onChange={(e) => setDraft({ ...draft, expected_guest_count: Number(e.target.value) || 0 })}
                  className={`${inputCls} tabular-nums`} />
                <p className="text-[10px] mt-1" style={{ color: 'var(--v-text-dim)' }}>Was: {(effective.expected_guest_count ?? 0).toLocaleString()}</p>
              </>
            ) : (
              <FieldDisplay locked={isEditing && lockMatrix.guests}>{(effective.expected_guest_count ?? 0).toLocaleString()}</FieldDisplay>
            )}
          </div>

          {/* Created */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-0.5" style={{ color: 'var(--v-text-muted)' }}>Created</p>
            <p className="font-medium" style={{ color: 'var(--v-text)' }}>{formatDate(effective.created_at)}</p>
          </div>
        </div>
      </div>

      {/* Bar list (live event only) */}
      {effectiveIsLive && (
        <div className="v-card overflow-hidden">
          <div className="px-5 py-3 flex items-center justify-between" style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
            <h2 className="text-[11px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Bars</h2>
            <span className="text-xs" style={{ color: 'var(--v-text-muted)' }}>{realBarsCount} bars</span>
          </div>
          {barsQuery.isLoading ? (
            <div className="px-5 py-8 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>Loading bars…</div>
          ) : barsQuery.isError ? (
            <div className="px-5 py-8 text-center text-sm" style={{ color: 'var(--v-pink)' }}>Failed to load bars.</div>
          ) : realBars.length === 0 ? (
            <div className="px-5 py-8">
              <EmptyState headline="No bars configured" body="No bars configured for this event yet." />
            </div>
          ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: '0.5px solid var(--v-border)' }}>
                <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Name</th>
                <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Type</th>
                <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {realBars.map((bar) => (
                <tr
                  key={bar.id}
                  className="last:border-0 transition-colors"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-5 py-3 font-medium" style={{ color: 'var(--v-text)' }}>{bar.name}</td>
                  <td className="px-5 py-3 capitalize" style={{ color: 'var(--v-text-muted)' }}>{bar.bar_type}</td>
                  <td className="px-5 py-3 text-right">
                    {bar.is_active ? (
                      <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: 'var(--v-green)' }}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--v-green)' }} />
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: 'var(--v-text-dim)' }}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--v-text-dim)' }} />
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
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(8,9,13,0.72)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
          onClick={() => setShowGoLiveConfirm(false)}
        >
          <div className="max-w-md w-full mx-4 p-6" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'rgba(61, 255, 163, 0.12)' }}>
                <svg className="w-5 h-5" style={{ color: 'var(--v-green)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>Go Live with {effective.name}?</h3>
                <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>This opens the POS, activates dashboards, and begins live data collection. The event configuration becomes locked.</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="secondary" onClick={() => setShowGoLiveConfirm(false)}>Cancel</Button>
              <Button variant="primary" onClick={handleGoLiveConfirmed}>Yes, Go Live</Button>
            </div>
          </div>
        </div>
      )}

      {/* Go Live Destination Choice Modal */}
      {showGoLiveDestination && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(8,9,13,0.72)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
          onClick={() => setShowGoLiveDestination(false)}
        >
          <div className="max-w-md w-full mx-4 p-6" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'rgba(0, 229, 212, 0.12)' }}>
                <svg className="w-5 h-5" style={{ color: 'var(--v-cyan)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>{effective.name} is now live</h3>
                <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>Where do you want to go next?</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="secondary" onClick={() => setShowGoLiveDestination(false)}>Stay on Detail</Button>
              <Button variant="primary" onClick={handleGoToDashboard}>Open Dashboard</Button>
            </div>
          </div>
        </div>
      )}

      {/* End Event Confirmation Modal */}
      {showEndConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(8,9,13,0.72)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
          onClick={() => setShowEndConfirm(false)}
        >
          <div className="max-w-md w-full mx-4 p-6" style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'rgba(255, 61, 113, 0.12)' }}>
                <svg className="w-5 h-5" style={{ color: 'var(--v-pink)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <div>
                <h3 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>End {effective.name}?</h3>
                <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>This will lock the event, freeze all sales data, and start generating the post-event report. This cannot be undone.</p>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <Button variant="secondary" onClick={() => setShowEndConfirm(false)}>Cancel</Button>
              <button
                onClick={handleEndConfirmed}
                className="text-sm font-semibold px-4 py-2 rounded-[var(--v-radius-sm)] transition-colors"
                style={{ color: 'var(--v-bg-base)', background: 'var(--v-pink)' }}
              >
                Yes, End Event
              </button>
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
        <div className="flex items-center gap-3" style={{ color: 'var(--v-text-muted)' }}>
          <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
          <span className="text-sm">Loading event\u2026</span>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="rounded-[var(--v-radius-lg)] p-5" style={{ background: 'rgba(255, 61, 113, 0.08)', border: '0.5px solid var(--v-pink)' }}>
          <p className="text-sm font-semibold" style={{ color: 'var(--v-pink)' }}>Failed to load event.</p>
          {error instanceof Error && (
            <p className="text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>{error.message}</p>
          )}
          <button
            onClick={() => navigate('/events')}
            className="mt-3 text-sm font-semibold hover:underline"
            style={{ color: 'var(--v-cyan)' }}
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
        <div className="v-card p-5">
          <p className="text-sm font-semibold" style={{ color: 'var(--v-text)' }}>Event not found.</p>
          <p className="text-xs mt-1" style={{ color: 'var(--v-text-muted)' }}>
            The event may have been deleted or you do not have access.
          </p>
          <button
            onClick={() => navigate('/events')}
            className="mt-3 text-sm font-semibold hover:underline"
            style={{ color: 'var(--v-cyan)' }}
          >
            \u2190 Back to Events
          </button>
        </div>
      </div>
    )
  }

  return <EventDetailContent event={event} />
}
