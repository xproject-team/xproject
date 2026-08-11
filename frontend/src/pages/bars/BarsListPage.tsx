import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useBars } from '@/features/bars/hooks'
import { useEvents } from '@/features/events/hooks'
import type { BarRow, BarType, Event } from '@/lib/mockData'
import { Badge, Button, EmptyState, PageHeader } from '@/design-system/components'
import '@/design-system/components/components.css'

// ─── DATA SOURCE ──────────────────────────────────────────────────────────────
// Bars are fetched via useBars(eventId) — TanStack Query → /api/v1/bars.
// Defaults to the currently live event (or the most recently scheduled one if
// none is live) so the list isn't 208 bars across every event at once.
// "All events" stays available in the dropdown for the global view.

function getEffectiveStatus(event: Event): Event['status'] {
  if (event.status === 'live' && event.ended_at) {
    const ended = new Date(event.ended_at).getTime()
    if (Number.isFinite(ended) && ended < Date.now()) return 'completed'
  }
  return event.status
}

function computeDefaultEventId(events: Event[]): string {
  const live = events.find((e) => getEffectiveStatus(e) === 'live')
  if (live) return live.id
  const mostRecent = [...events].sort(
    (a, b) => new Date(b.scheduled_at).getTime() - new Date(a.scheduled_at).getTime(),
  )[0]
  return mostRecent?.id ?? ''
}

// ─── Active/Inactive filter pills ──────────────────────────────────────────────

type FilterKey = 'all' | 'active' | 'inactive'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all',      label: 'All'      },
  { key: 'active',   label: 'Active'   },
  { key: 'inactive', label: 'Inactive' },
]

function FilterPill({ label, count, isActive, onClick }: {
  label: string
  count: number
  isActive: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="text-xs font-medium px-3 py-1.5 rounded-full transition-colors"
      style={{
        background: isActive ? 'rgba(0, 229, 212, 0.12)' : 'var(--v-surface)',
        color: isActive ? 'var(--v-cyan)' : 'var(--v-text-muted)',
        border: `0.5px solid ${isActive ? 'var(--v-cyan)' : 'var(--v-border)'}`,
      }}
    >
      {label} <span className="opacity-75">({count})</span>
    </button>
  )
}

// ─── Type badge ─────────────────────────────────────────────────────────────────

const TYPE_CFG: Record<BarType, { label: string; variant: 'info' | 'violet' | 'neutral' | 'warning' | 'success' }> = {
  drinks:  { label: 'Drinks',  variant: 'info'    },
  food:    { label: 'Food',    variant: 'violet'  },
  mixed:   { label: 'Mixed',   variant: 'warning' },
  merch:   { label: 'Merch',   variant: 'success' },
  service: { label: 'Service', variant: 'neutral' },
}

function TypeBadge({ type }: { type: BarType }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG.drinks
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>
}

// ─── Slesh ID cell — the POS mapping column ────────────────────────────────────
// This column matters most: a missing Slesh ID means live orders from that
// bar arrive unmapped. A bare dash used to be the only signal — now a missing
// value is an amber "Not linked" badge, and a present value is copyable.

function ClipboardIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  )
}

function SleshIdCell({ value }: { value: string | null }) {
  const [copied, setCopied] = useState(false)

  if (!value) {
    return <Badge variant="warning">Not linked</Badge>
  }

  const truncated = value.length > 14 ? `${value.slice(0, 14)}…` : value

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Best-effort affordance — nothing to surface if the Clipboard API is unavailable.
    }
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 font-mono text-xs"
      style={{ color: 'var(--v-text-muted)' }}
      title={value}
    >
      {truncated}
      <button
        onClick={handleCopy}
        aria-label="Copy Slesh ID"
        title={copied ? 'Copied' : 'Copy'}
        className="transition-opacity opacity-60 hover:opacity-100"
        style={{ color: copied ? 'var(--v-green)' : 'var(--v-text-dim)' }}
      >
        {copied ? <CheckIcon /> : <ClipboardIcon />}
      </button>
    </span>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function BarsListPage() {
  const navigate = useNavigate()

  const { data: events = [] } = useEvents()

  // null = default not yet resolved (waiting on events to load);
  // ''   = user explicitly chose "All events";
  // otherwise a specific event id.
  const [eventId, setEventId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<FilterKey>('all')

  useEffect(() => {
    if (eventId === null && events.length > 0) {
      setEventId(computeDefaultEventId(events))
    }
  }, [events, eventId])

  const {
    data: bars = [],
    isLoading: barsLoading,
    isError,
    error,
  } = useBars(eventId === null ? undefined : eventId || undefined)

  // Don't render "all bars" even for one frame while the default is resolving.
  const isLoading = barsLoading || eventId === null

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

  const notLinkedCount = useMemo(
    () => bars.filter((b) => !b.slesh_negozio_id).length,
    [bars],
  )

  const subtitle = (
    <>
      {counts.all} bar{counts.all === 1 ? '' : 's'} · {counts.active} active
      {notLinkedCount > 0 && (
        <span style={{ color: 'var(--v-amber)' }}>
          {' '}· {notLinkedCount} bar{notLinkedCount === 1 ? '' : 's'} not linked to a POS shop
        </span>
      )}
    </>
  )

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <PageHeader
          title="Bars"
          subtitle={subtitle}
          actions={
            <Button variant="primary" onClick={() => navigate('/bars/new')}>
              <span className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Create Bar
              </span>
            </Button>
          }
        />
      </div>

      {/* Filters row */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--v-text-muted)' }}>
          Event:
          <select
            value={eventId ?? ''}
            onChange={(e) => setEventId(e.target.value)}
            className="text-xs rounded-[var(--v-radius-sm)] px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--v-cyan)]/30"
            style={{ background: 'var(--v-bg-base)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}
          >
            <option value="">All events</option>
            {events.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </label>

        <div className="flex gap-1.5 ml-2">
          {FILTERS.map((f) => (
            <FilterPill
              key={f.key}
              label={f.label}
              count={counts[f.key]}
              isActive={activeTab === f.key}
              onClick={() => setActiveTab(f.key)}
            />
          ))}
        </div>
      </div>

      {/* Table */}
      <div
        className="overflow-hidden"
        style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
      >
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Name</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Type</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Event</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Slesh ID</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Status</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
                  <div className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                    Loading bars…
                  </div>
                </td>
              </tr>
            )}

            {isError && !isLoading && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center">
                  <div className="inline-flex items-start gap-2 text-sm" style={{ color: 'var(--v-pink)' }}>
                    <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>
                      Failed to load bars.
                      {error instanceof Error && <span className="block text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>{error.message}</span>}
                    </span>
                  </div>
                </td>
              </tr>
            )}

            {!isLoading && !isError && visibleBars.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-12">
                  <EmptyState
                    headline={bars.length === 0 ? 'No bars for this event' : `No ${activeTab} bars`}
                    body={bars.length === 0 ? 'Click "Create Bar" to add one.' : 'Try a different filter.'}
                  />
                </td>
              </tr>
            )}

            {!isLoading && !isError && visibleBars.map((bar) => {
              const textColor = bar.is_active ? 'var(--v-text)' : 'var(--v-text-muted)'
              return (
                <tr
                  key={bar.id}
                  className="transition-colors last:border-0"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-5 py-4 font-medium" style={{ color: textColor }}>{bar.name}</td>
                  <td className="px-5 py-4"><TypeBadge type={bar.bar_type} /></td>
                  <td className="px-5 py-4 text-xs" style={{ color: 'var(--v-text-muted)' }}>
                    {eventNameById.get(bar.event_id) ?? '(unknown)'}
                  </td>
                  <td className="px-5 py-4"><SleshIdCell value={bar.slesh_negozio_id} /></td>
                  <td className="px-5 py-4">
                    <Badge variant={bar.is_active ? 'success' : 'neutral'}>
                      {bar.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <Button variant="secondary" onClick={() => navigate(`/bars/${bar.id}`)}>
                      View
                    </Button>
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
