/**
 * BarDetailOverlay - slides in from the right when a BarCard is clicked.
 *
 * Step 7b wire-up (April 17 2026):
 * - 7b.1: accepts BarKpi, real header + revenue number + drinks breakdown
 * - 7b.2: real cumulative revenue chart via adaptive bucketing (this revision)
 * - 7b.3: chart pan/zoom/crosshair (next)
 * - 7b.4: per-product stock table (next)
 * - 7b.5: chat section wiring (next)
 * - Alerts section: silent hide until alerts backend (v1.1)
 *
 * Day 4/5 restyle: converted to the Vera Event design system + relaid out
 * (hero chart full-width on top, 2-col grid for breakdown/stock/alerts,
 * chat full-width at the bottom).
 *
 * Day 6 fix: every section now reads the event the dashboard actually
 * resolved (eventId/eventStartMs/nowMs/isLive, threaded down from
 * DashboardContent) instead of independently re-deriving "whatever event
 * is live right now" via useLiveEvent(). That mismatch was the source of
 * the post-event bug — completed events have no live event, so every
 * section here read as empty even though the dashboard cards for the
 * same event showed real data. useLiveEvent() is no longer used in this
 * file; every hook it touches already accepted an explicit eventId.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useAllProducts,
  useBarSupplierStock,
  useTransactionsForEvent,
  useBarCategoryTotals,
} from '@/features/dashboard/hooks'
import { BarMiniChart } from '@/features/dashboard/BarMiniChart'
import {
  BarCategoryBreakdown,
  BarTopDrinks,
} from '@/features/dashboard/BarCategoryBreakdown'
import type { ProductLike } from '@/features/dashboard/category-resolver'
import type { BarKpi, BarStatus } from '@/lib/mockData'
import {
  useChannels,
  useChannelMessages,
  usePostMessage,
  useMarkChannelRead,
} from '@/features/chat/useChat'
import { useAlertsForEvent, useAcknowledgeAlert } from '@/features/alerts/useAlerts'
import { Badge, Button, EmptyState, type BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'

const STATUS_DOT: Record<BarStatus, string> = {
  healthy: 'var(--v-green)',
  warning: 'var(--v-amber)',
  critical: 'var(--v-pink)',
}

const STATUS_BADGE: Record<BarStatus, { text: string; variant: BadgeVariant }> = {
  healthy: { text: 'Healthy', variant: 'success' },
  warning: { text: 'Low Stock', variant: 'warning' },
  critical: { text: 'Critical', variant: 'danger' },
}

function SectionHeader({ title }: { title: string }) {
  return (
    <h2
      className="text-[11px] font-semibold uppercase tracking-[0.06em] mb-3 pb-2"
      style={{ color: 'var(--v-text-muted)', borderBottom: '0.5px solid var(--v-border)' }}
    >
      {title}
    </h2>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return <section className="v-card p-4">{children}</section>
}

// Revenue chart subcomponent — DASH.4 rewrite (May 27 2026).
// Renders a TALL multi-line chart matching the per-card BarMiniChart:
// 5 lines (total + beer / cocktails / premium_cocktails / wine).
// Same data + same colors as the card chart, just bigger with legend
// and Y-axis visible. Locked May 27 2026 with Hesam.
//
// eventStartMs/nowMs are passed down from DashboardContent — the exact
// same values already used for the main dashboard chart and every
// BarCard's mini chart — instead of re-derived from useLiveEvent(),
// which only ever has a value while some event is live.
interface RevenueChartProps {
  barId: string
  eventId: string
  eventStartMs: number
  nowMs: number
}

function RevenueChart({ barId, eventId, eventStartMs, nowMs }: RevenueChartProps) {
  const transactionsQuery  = useTransactionsForEvent(eventId)
  const productsQuery      = useAllProducts()

  if (transactionsQuery.isLoading || productsQuery.isLoading) {
    return (
      <div className="h-56 flex items-center justify-center text-xs italic" style={{ color: 'var(--v-text-muted)' }}>
        Loading chart data...
      </div>
    )
  }

  return (
    <BarMiniChart
      barId={barId}
      transactions={transactionsQuery.data ?? []}
      products={(productsQuery.data ?? []) as ProductLike[]}
      eventStartMs={eventStartMs}
      nowMs={nowMs}
      height={280}
      showLegend
    />
  )
}

// ─── Stock table — Phase 3 ml-depletion (Sundance 14) ─────────────

interface StockTableProps {
  barId: string
  eventId: string | null | undefined
}

function StockTable({ barId, eventId }: StockTableProps) {
  // Phase 3 — Sundance 14: reads from /bar-supplier-stock which exposes
  // per-(bar, supplier_product) ml-depletion math from event_category_
  // ingredients. Backend simultaneously fires depletion alerts on
  // threshold flips (worst-case high-recall design).
  const stockQuery = useBarSupplierStock(eventId, barId)

  if (stockQuery.isLoading) {
    return (
      <div className="text-xs italic py-6 text-center" style={{ color: 'var(--v-text-muted)' }}>
        Loading stock…
      </div>
    )
  }
  const items = stockQuery.data?.items ?? []
  // Sort: critical first, then by remaining_pct ascending (most-empty first)
  const rows = [...items].sort((a, b) => {
    const sev = (s: string) => (s === 'critical' ? 0 : s === 'low' ? 1 : 2)
    if (sev(a.status) !== sev(b.status)) return sev(a.status) - sev(b.status)
    return a.remaining_pct - b.remaining_pct
  })

  if (rows.length === 0) {
    return <EmptyState headline="No stock dispatched" body="No stock dispatched to this bar yet." />
  }

  return (
    <div className="space-y-2">
      {rows.map((r) => {
        // Color by status
        const barColor =
          r.status === 'critical' ? 'var(--v-pink)'
          : r.status === 'low'    ? 'var(--v-amber)'
          :                         'var(--v-green)'
        const statusBadge =
          r.status === 'critical' ? '🔴 CRITICAL'
          : r.status === 'low'    ? '🟡 LOW'
          :                         '🟢 HEALTHY'
        // ml display: prefer ml; for whole bottles (vol_per_unit ≤ 750ml
        // and integer dispatched_units), show "X / Y units"
        const pctClamped = Math.max(0, Math.min(100, r.remaining_pct))
        return (
          <div
            key={r.supplier_product_id}
            className="rounded-[var(--v-radius)] p-3"
            style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)' }}
          >
            <div className="flex items-center justify-between mb-1.5 gap-2">
              <span className="text-sm font-medium truncate" style={{ color: 'var(--v-text)' }} title={r.item_name}>
                {r.item_name}
              </span>
              <div className="flex items-center gap-1.5 shrink-0">
                {r.accurate && (
                  <span
                    className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded"
                    style={{ background: 'rgba(61, 255, 163, 0.12)', color: 'var(--v-green)', border: '0.5px solid var(--v-green)' }}
                    title="Sole ingredient — exact depletion (no worst-case)"
                  >
                    accurate
                  </span>
                )}
                <span className="text-[10px] font-bold uppercase tracking-wide tabular-nums" style={{ color: barColor }}>
                  {statusBadge}
                </span>
              </div>
            </div>
            {/* Loading bar */}
            <div className="w-full h-3 rounded-full overflow-hidden" style={{ background: 'var(--v-border)' }}>
              <div
                className="h-full transition-all duration-500"
                style={{ width: `${pctClamped}%`, backgroundColor: barColor }}
              />
            </div>
            <div className="flex items-center justify-between mt-1 text-[11px]" style={{ color: 'var(--v-text-muted)' }}>
              <span className="tabular-nums">
                {Math.round(r.remaining_ml).toLocaleString()} ml / {Math.round(r.dispatched_ml).toLocaleString()} ml
              </span>
              <span className="tabular-nums font-semibold" style={{ color: barColor }}>
                {Math.round(pctClamped)}%
              </span>
            </div>
            {(r.consumed_ml_certain > 0 || r.consumed_ml_uncertain > 0) && (
              <div className="flex items-center gap-3 mt-1 text-[10px] tabular-nums" style={{ color: 'var(--v-text-dim)' }}>
                {r.consumed_ml_certain > 0 && (
                  <span title="From sole-ingredient categories — exact attribution">
                    <span className="font-semibold" style={{ color: 'var(--v-green)' }}>●</span>{' '}
                    {Math.round(r.consumed_ml_certain).toLocaleString()} ml certain
                  </span>
                )}
                {r.consumed_ml_uncertain > 0 && (
                  <span title="From multi-ingredient categories — worst-case attribution">
                    <span className="font-semibold" style={{ color: 'var(--v-amber)' }}>●</span>{' '}
                    up to {Math.round(r.consumed_ml_uncertain).toLocaleString()} ml worst-case
                  </span>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Chat section - intentional v1.1 placeholder with explicit sync contract
// pointer. The overlay chat is designed to be a MINI-VIEW of the full sidebar
// Chat page: when Omar messages a bar manager from here, the same conversation
// appears in the sidebar Chat -> that bar's manager branch, and vice versa.
// The sync mechanism (shared TanStack Query keys, single cache, WebSocket
// invalidation) is specified in docs/chat-module-spec.md section 6.
// Until the Chat module ships, messages below are sample data and the input
// field is local-only (no network, no persistence, no sync).

// Chat section — mini-view of the full sidebar Chat page for THIS bar's channel.
// Shares TanStack Query keys with /pages/chat/ChatPage so messages sent/received
// here appear instantly in the sidebar and vice versa, no refetch needed.
// The bar's channel is resolved by finding the unique bar-type channel where
// bar_id === this bar. Channels are auto-created when a bar is created (see
// commit e7c275d); for legacy/bulk-imported bars, Owner can trigger the
// backfill endpoint POST /api/v1/bars/backfill-channels.

interface ChatSectionProps {
  barId: string
  barName: string
}

function ChatSection({ barId, barName }: ChatSectionProps) {
  const channelsQuery = useChannels()

  // Resolve the bar-team channel for THIS specific bar
  const channel = useMemo(() => {
    if (!channelsQuery.data) return null
    return channelsQuery.data.find(
      (c) => c.channel_type === 'bar' && c.bar_id === barId,
    ) ?? null
  }, [channelsQuery.data, barId])

  // Loading channel list
  if (channelsQuery.isLoading) {
    return (
      <p className="text-xs italic py-6 text-center" style={{ color: 'var(--v-text-muted)' }}>
        Loading chat&hellip;
      </p>
    )
  }

  // Channel list loaded but no bar-team channel exists for this bar.
  // Shouldn't happen for newly-created bars (auto-hook) but can for bars
  // that pre-date the auto-hook without being backfilled.
  if (channel === null) {
    return <EmptyState headline="No chat channel" body="No chat channel for this bar yet." />
  }

  return <ChatSectionInner channel={channel} barName={barName} />
}

// Inner component: channel guaranteed non-null, hooks safe to call.
// Pattern matches EventDetailPage/Content split to avoid Rules-of-Hooks issues.
interface ChatSectionInnerProps {
  channel: { id: string; name: string }
  barName: string
}

function ChatSectionInner({ channel, barName }: ChatSectionInnerProps) {
  const [input, setInput] = useState('')

  const messagesQuery = useChannelMessages(channel.id, 20)
  const postMessage = usePostMessage(channel.id)
  const markRead = useMarkChannelRead(channel.id)

  // Mark this channel as read once when the overlay opens on it.
  // Runs once per channel-change, not on every message arrival.
  useEffect(() => {
    markRead.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.id])

  function handleSend() {
    const body = input.trim()
    if (!body || postMessage.isPending) return
    postMessage.mutate(
      { body },
      {
        onSuccess: () => setInput(''),
      },
    )
  }

  const messages = messagesQuery.data ?? []
  // API returns newest-first; render oldest-first for natural reading order
  const ordered = [...messages].reverse()

  return (
    <>
      {messagesQuery.isLoading ? (
        <p className="text-xs italic mb-4 py-4 text-center" style={{ color: 'var(--v-text-muted)' }}>
          Loading messages&hellip;
        </p>
      ) : ordered.length > 0 ? (
        <div className="space-y-2 mb-4 max-h-64 overflow-y-auto pr-1">
          {ordered.map((msg) => (
            <div
              key={msg.id}
              className="rounded-[var(--v-radius)] px-3 py-2.5"
              style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)' }}
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs font-semibold" style={{ color: 'var(--v-text)' }}>
                  {msg.sender_name ?? 'Unknown sender'}
                </span>
                <span className="text-[10px] font-mono" style={{ color: 'var(--v-text-dim)' }}>
                  {new Date(msg.created_at).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              <p className="text-xs leading-snug" style={{ color: 'var(--v-text-muted)' }}>{msg.body}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs italic mb-4 py-4 text-center" style={{ color: 'var(--v-text-muted)' }}>
          No messages for this bar yet.
        </p>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSend() }}
          placeholder={'Send message to ' + barName + ' manager...'}
          disabled={postMessage.isPending}
          className="flex-1 text-sm rounded-lg px-3 py-2 focus:outline-none transition disabled:opacity-60"
          style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}
        />
        <Button variant="primary" onClick={handleSend} disabled={!input.trim() || postMessage.isPending}>
          {postMessage.isPending ? 'Sending…' : 'Send'}
        </Button>
      </div>
    </>
  )
}
interface Props {
  bar: BarKpi | null
  onClose: () => void
  /** The event the dashboard is currently showing — live, completed, or
   *  preview. Every data-fetching section below reads THIS event, not
   *  whatever happens to be tenant-wide live right now. */
  eventId: string
  /** Same values DashboardContent already computes for the main chart
   *  and every BarCard's mini chart — reused here, not re-derived. */
  eventStartMs: number
  nowMs: number
  /** True only while eventId's own status is 'live'. Drives the "Live
   *  event" pill — distinct from "is some other event live somewhere". */
  isLive: boolean
}

// AlertsSection - Apr 20 2026 cross-page integration
interface AlertsSectionProps { barId: string; eventId: string | null }
function AlertsSection({ barId, eventId }: AlertsSectionProps) {
  const alertsQuery = useAlertsForEvent(eventId, { onlyActive: true })
  const ackMutation = useAcknowledgeAlert()
  const alerts = (alertsQuery.data?.items ?? []).filter((a) => a.bar_id === barId)
  if (alerts.length === 0) {
    return <EmptyState headline="No active alerts" body="No active alerts for this bar." />
  }
  return (
    <div className="space-y-3">
      {alerts.map((alert) => {
        const isCritical = alert.severity === 'critical'
        const isWarning = alert.severity === 'warning'
        const color = isCritical ? 'var(--v-pink)' : isWarning ? 'var(--v-amber)' : 'var(--v-cyan)'
        const variant: BadgeVariant = isCritical ? 'danger' : isWarning ? 'warning' : 'info'
        return (
          <div
            key={alert.id}
            className="rounded-[var(--v-radius)] p-3"
            style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderLeft: `3px solid ${color}` }}
          >
            <div className="flex items-start justify-between gap-3 mb-1.5">
              <Badge variant={variant}>{alert.severity}</Badge>
              <button
                onClick={() => ackMutation.mutate({ alert_id: alert.id, version: alert.version })}
                disabled={ackMutation.isPending}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-md transition-colors disabled:opacity-50"
                style={{ color: 'var(--v-text-muted)', border: '0.5px solid var(--v-border)', background: 'var(--v-surface-raised)' }}
              >
                Acknowledge
              </button>
            </div>
            <p className="text-[11px] font-bold mb-1" style={{ color: 'var(--v-text)' }}>{alert.title}</p>
            <p className="text-[12px] leading-snug" style={{ color: 'var(--v-text-muted)' }}>{alert.message}</p>
            {alert.suggested_action && (
              <p className="mt-2 text-[11px] italic" style={{ color: 'var(--v-text-dim)' }}>{'→ ' + alert.suggested_action}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function BarDetailOverlay({ bar, onClose, eventId, eventStartMs, nowMs, isLive }: Props) {
  const isOpen = bar !== null

  const prevBarRef = useRef<BarKpi | null>(null)
  if (bar !== null) prevBarRef.current = bar
  const b = bar ?? prevBarRef.current

  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  // DASH.6 — fetch per-bar category totals for the Drinks Breakdown section.
  const categoryTotalsQuery = useBarCategoryTotals(eventId)
  const barCategoryRow =
    categoryTotalsQuery.data?.bars.find((br) => br.bar_id === b?.id) ?? null

  const revenueEuros = b ? Math.round(b.revenue_cents / 100) : 0

  return (
    <>
      <div
        className="fixed inset-0 z-40 transition-opacity duration-300"
        style={{
          background: 'rgba(8,9,13,0.72)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
        }}
        onClick={onClose}
      />

      <div
        className="fixed right-0 top-0 h-full w-[70%] z-50 flex flex-col transition-transform duration-300 ease-in-out"
        style={{
          background: 'var(--v-surface-raised)',
          borderLeft: '0.5px solid var(--v-border)',
          transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        }}
      >
        {b && (
          <>
            <header
              className="flex items-center justify-between px-6 py-4 shrink-0"
              style={{ borderBottom: '0.5px solid var(--v-border)' }}
            >
              <div className="flex items-center gap-2.5">
                <div className="w-3 h-3 rounded-full shrink-0" style={{ background: STATUS_DOT[b.status] }} />
                <h1 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>{b.name}</h1>
                <Badge variant={STATUS_BADGE[b.status].variant}>{STATUS_BADGE[b.status].text}</Badge>
                {isLive && <Badge variant="info">Live event</Badge>}
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="w-8 h-8 flex items-center justify-center rounded-full transition-colors"
                style={{ border: '0.5px solid var(--v-border)', color: 'var(--v-text-muted)' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-text)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-muted)')}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </header>

            <div className="flex-1 overflow-y-auto">
              <div className="p-6 space-y-3">

                {/* Hero — hourly stacked chart, full width, ~2x dashboard height */}
                <Card>
                  <SectionHeader title="Revenue" />
                  <div className="flex items-end gap-3 mb-4">
                    <p className="text-3xl font-medium" style={{ color: 'var(--v-text)' }}>
                      &euro;{revenueEuros.toLocaleString()}
                    </p>
                  </div>
                  <RevenueChart barId={b.id} eventId={eventId} eventStartMs={eventStartMs} nowMs={nowMs} />
                </Card>

                {/* Two-column grid, 12px gap: left = Drinks breakdown + Top 5,
                    right = Stock + Alerts. DOM order [breakdown, stock, top5,
                    alerts] over a 2-col grid naturally groups each pair into
                    its own column via row-major auto-flow. */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-stretch">
                  <Card>
                    <SectionHeader title={b.bar_type === 'food' ? 'Food Breakdown' : 'Drinks Breakdown'} />
                    {categoryTotalsQuery.isLoading ? (
                      <p className="text-sm italic" style={{ color: 'var(--v-text-muted)' }}>Loading breakdown...</p>
                    ) : (
                      <BarCategoryBreakdown bar={barCategoryRow} bar_type={b.bar_type} />
                    )}
                  </Card>

                  <Card>
                    <SectionHeader title="Stock" />
                    <StockTable barId={b.id} eventId={eventId} />
                  </Card>

                  <Card>
                    <SectionHeader title={b.bar_type === 'food' ? 'Top 5 items (by units)' : 'Top 5 drinks (by units)'} />
                    {categoryTotalsQuery.isLoading ? (
                      <p className="text-sm italic" style={{ color: 'var(--v-text-muted)' }}>Loading breakdown...</p>
                    ) : (
                      <BarTopDrinks bar={barCategoryRow} bar_type={b.bar_type} />
                    )}
                  </Card>

                  <Card>
                    <SectionHeader title="Alerts" />
                    <AlertsSection barId={b.id} eventId={eventId} />
                  </Card>
                </div>

                {/* Chat — full width */}
                <Card>
                  <SectionHeader title="Chat" />
                  <ChatSection barId={b.id} barName={b.name} />
                </Card>

              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
