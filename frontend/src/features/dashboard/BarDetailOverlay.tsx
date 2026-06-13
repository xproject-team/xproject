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
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  useAllProducts,
  useBarStockForEvent,
  useBurnRatesForEvent,
  useLiveEvent,
  useTransactionsForEvent,
  useBarCategoryTotals
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

// Style maps
const STATUS_DOT: Record<BarStatus, string> = {
  healthy: 'bg-[#38A169]',
  warning: 'bg-[#D69E2E]',
  critical: 'bg-[#E53E3E] animate-pulse',
}

const STATUS_LABEL: Record<BarStatus, { text: string; cls: string }> = {
  healthy: { text: 'Healthy', cls: 'bg-green-100 text-[#38A169]' },
  warning: { text: 'Low Stock', cls: 'bg-yellow-100 text-[#D69E2E]' },
  critical: { text: 'Critical', cls: 'bg-red-100 text-[#E53E3E]' },
}

function SectionHeader({ title }: { title: string }) {
  return (
    <h2 className="text-[10px] font-bold text-[#4A5568] uppercase tracking-widest mb-3 pb-2 border-b border-[#E2E8F0]">
      {title}
    </h2>
  )
}

// Revenue chart subcomponent — DASH.4 rewrite (May 27 2026).
// Renders a TALL multi-line chart matching the per-card BarMiniChart:
// 5 lines (total + beer / cocktails / premium_cocktails / wine).
// Same data + same colors as the card chart, just bigger with legend
// and Y-axis visible. Locked May 27 2026 with Hesam.
interface RevenueChartProps {
  barId: string
}

function RevenueChart({ barId }: RevenueChartProps) {
  const liveEventQuery     = useLiveEvent()
  const transactionsQuery  = useTransactionsForEvent(liveEventQuery.data?.id ?? null)
  const productsQuery      = useAllProducts()

  const eventStartIso = liveEventQuery.data?.started_at ?? null

  if (liveEventQuery.isLoading || transactionsQuery.isLoading || productsQuery.isLoading) {
    return (
      <div className="h-56 flex items-center justify-center text-xs text-[#A0AEC0] italic">
        Loading chart data...
      </div>
    )
  }

  if (!eventStartIso) {
    return (
      <div className="h-56 flex items-center justify-center text-xs text-[#A0AEC0] italic">
        No event start time available yet.
      </div>
    )
  }

  const eventStartMs = new Date(eventStartIso).getTime()
  const nowMs        = Date.now()

  return (
    <div className="space-y-2">
      <BarMiniChart
        barId={barId}
        transactions={transactionsQuery.data ?? []}
        products={(productsQuery.data ?? []) as ProductLike[]}
        eventStartMs={eventStartMs}
        nowMs={nowMs}
        height={280}
      />
      <p className="text-[10px] text-[#A0AEC0] italic">
        ML Predicted overlay arrives when MLPredictor is wired
        (Phase 2 resumption).
      </p>
    </div>
  )
}

// ─── Stock table (real per-product rows, sorted by stock% ascending) ────────

type DerivedStockStatus = 'depleted' | 'critical' | 'warning' | 'healthy'

const PRODUCT_STATUS_CFG: Record<DerivedStockStatus, { label: string; cls: string }> = {
  healthy: { label: 'Healthy', cls: 'bg-green-100 text-[#38A169] border border-green-200' },
  warning: { label: 'Warning', cls: 'bg-yellow-100 text-[#D69E2E] border border-yellow-200' },
  critical: { label: 'Critical', cls: 'bg-red-100 text-[#E53E3E] border border-red-200' },
  depleted: { label: 'Depleted', cls: 'bg-gray-100 text-[#718096] border border-gray-200' },
}

function deriveStockStatus(currentQty: number, allocatedQty: number): DerivedStockStatus {
  if (currentQty === 0) return 'depleted'
  if (allocatedQty === 0) return 'healthy'  // edge case: no allocation baseline
  const pct = (currentQty / allocatedQty) * 100
  if (pct > 60) return 'healthy'
  if (pct > 30) return 'warning'
  return 'critical'
}

interface StockTableProps {
  barId: string
  eventId: string | null | undefined
}

function StockTable({ barId, eventId }: StockTableProps) {
  const barStockQuery = useBarStockForEvent(eventId)
  const productsQuery = useAllProducts()
  const burnRatesQuery = useBurnRatesForEvent(eventId)

  if (barStockQuery.isLoading || productsQuery.isLoading || burnRatesQuery.isLoading) {
    return (
      <div className="text-xs text-[#A0AEC0] italic py-6 text-center">
        Loading stock&hellip;
      </div>
    )
  }

  const allStock = barStockQuery.data ?? []
  const products = productsQuery.data ?? []
  const burnRates = burnRatesQuery.data ?? []
  const brByKey = new Map(burnRates.map((r) => [r.bar_id + ":" + r.product_id, r]))

  // Index products for O(1) join
  const productById = new Map(products.map((p) => [p.id, p]))

  // Filter to this bar, compute derived fields, sort by stock% ascending
  const rows = allStock
    .filter((s) => s.bar_id === barId)
    .map((s) => {
      const product = productById.get(s.product_id)
      const pct = s.allocated_qty === 0
        ? 0
        : Math.round((s.current_qty / s.allocated_qty) * 100)
      const br = brByKey.get(s.bar_id + ":" + s.product_id)
      return {
        stockId: s.id,
        productId: s.product_id,
        burnRate: br ? parseFloat(br.burn_rate_per_hour) : null,
        burnLabel: br ? br.window_label : null,
        depletionMin: br && br.time_to_depletion_min !== null ? parseFloat(br.time_to_depletion_min) : null,
        productName: product?.name ?? 'Unknown product',
        category: product?.category ?? '—',
        currentQty: s.current_qty,
        allocatedQty: s.allocated_qty,
        unit: product?.unit ?? 'units',
        pct,
        status: deriveStockStatus(s.current_qty, s.allocated_qty),
      }
    })
    .sort((a, b) => a.pct - b.pct)  // ascending: most urgent first

  if (rows.length === 0) {
    return (
      <div className="text-xs text-[#A0AEC0] italic py-6 text-center">
        No stock allocated at this bar yet.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[#E2E8F0]">
            {['Product', 'Category', 'Stock', 'Status', 'Burn Rate', 'Depletion'].map((h) => (
              <th
                key={h}
                className="text-left text-[10px] font-bold text-[#4A5568] uppercase tracking-wide py-2 pr-3 whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const st = PRODUCT_STATUS_CFG[r.status]
            const urgent = r.status === 'critical' || r.status === 'depleted'
            return (
              <tr
                key={r.stockId}
                className={[
                  'border-b border-[#F7FAFC]',
                  urgent ? 'bg-red-50/50' : 'hover:bg-[#F7FAFC]',
                ].join(' ')}
              >
                <td className="py-2.5 pr-3 font-medium text-[#1A202C] whitespace-nowrap">
                  {r.productName}
                </td>
                <td className="py-2.5 pr-3 text-[#4A5568]">{r.category}</td>
                <td
                  className="py-2.5 pr-3 font-mono text-[#1A202C] whitespace-nowrap"
                  title={'Started with ' + r.allocatedQty + ' ' + r.unit}
                >
                  {r.currentQty}/{r.allocatedQty}
                  <span className="text-[#4A5568] ml-1">({r.pct}%)</span>
                </td>
                <td className="py-2.5 pr-3">
                  <span className={'text-[10px] font-bold px-1.5 py-0.5 rounded-full ' + st.cls}>
                    {st.label}
                  </span>
                </td>
                <td
                  className={"py-2.5 pr-3 font-mono whitespace-nowrap " + (r.burnRate === null ? "text-[#A0AEC0] italic" : "text-[#1A202C]")}
                  title={r.burnRate === null ? "No recent sales — burn rate will appear once transactions arrive" : ({last_30m: "Rate over last 30 minutes", last_60m: "Rate over last hour", last_120m: "Rate over last 2 hours", event_wide: "Rate averaged over the full event"}[r.burnLabel ?? "event_wide"] ?? "Rate computed from event data")}
                >
                  {r.burnRate === null ? "—" : r.burnRate.toFixed(1) + " " + r.unit + "/h"}
                </td>
                <td
                  className={"py-2.5 font-mono whitespace-nowrap " + (r.depletionMin === null ? "text-[#A0AEC0] italic" : "text-[#1A202C]")}
                  title={r.depletionMin === null ? "No depletion estimate yet" : "Estimated at current rate"}
                >
                  {r.depletionMin === null || r.currentQty === 0 ? "—" : r.depletionMin < 60 ? Math.round(r.depletionMin) + "m" : Math.floor(r.depletionMin/60) + "h" + Math.round(r.depletionMin%60) + "m"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
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
      <p className="text-xs text-[#A0AEC0] italic py-6 text-center">
        Loading chat&hellip;
      </p>
    )
  }

  // Channel list loaded but no bar-team channel exists for this bar.
  // Shouldn't happen for newly-created bars (auto-hook) but can for bars
  // that pre-date the auto-hook without being backfilled.
  if (channel === null) {
    return (
      <p className="text-xs text-[#A0AEC0] italic py-6 text-center">
        No chat channel for this bar yet.
      </p>
    )
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
        <p className="text-xs text-[#A0AEC0] italic mb-4 py-4 text-center">
          Loading messages&hellip;
        </p>
      ) : ordered.length > 0 ? (
        <div className="space-y-2 mb-4 max-h-64 overflow-y-auto pr-1">
          {ordered.map((msg) => (
            <div
              key={msg.id}
              className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2.5"
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs font-semibold text-[#1A202C]">
                  {msg.sender_name ?? 'Unknown sender'}
                </span>
                <span className="text-[10px] font-mono text-[#4A5568]">
                  {new Date(msg.created_at).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              <p className="text-xs text-[#4A5568] leading-snug">{msg.body}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-[#A0AEC0] italic mb-4 py-4 text-center">
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
          className="flex-1 text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 bg-white text-[#1A202C] placeholder:text-[#CBD5E0] focus:outline-none focus:ring-2 focus:ring-[#1ABC9C]/30 focus:border-[#1ABC9C] transition disabled:opacity-60"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || postMessage.isPending}
          className="px-4 py-2 text-sm font-semibold text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: '#1ABC9C' }}
          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#17a589')}
          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#1ABC9C')}
        >
          {postMessage.isPending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </>
  )
}
interface Props {
  bar: BarKpi | null
  onClose: () => void
}

// AlertsSection - Apr 20 2026 cross-page integration
interface AlertsSectionProps { barId: string; eventId: string | null }
function AlertsSection({ barId, eventId }: AlertsSectionProps) {
  const alertsQuery = useAlertsForEvent(eventId, { onlyActive: true })
  const ackMutation = useAcknowledgeAlert()
  const alerts = (alertsQuery.data?.items ?? []).filter((a) => a.bar_id === barId)
  if (alerts.length === 0) {
    return <p className="text-sm text-[#718096] italic">No active alerts for this bar.</p>
  }
  return (
    <div className="space-y-3">
      {alerts.map((alert) => {
        const isCritical = alert.severity === 'critical'
        const isWarning = alert.severity === 'warning'
        const pillCls = isCritical ? 'bg-red-100 text-[#E53E3E] border-red-200'
          : isWarning ? 'bg-amber-100 text-[#B7791F] border-amber-200'
          : 'bg-blue-100 text-[#2B6CB0] border-blue-200'
        const borderCls = isCritical ? 'border-[#E53E3E] bg-red-50'
          : isWarning ? 'border-[#D69E2E] bg-amber-50'
          : 'border-[#3182CE] bg-blue-50'
        return (
          <div key={alert.id} className={'rounded-lg border-l-4 p-3 ' + borderCls}>
            <div className="flex items-start justify-between gap-3 mb-1.5">
              <span className={'text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ' + pillCls}>
                {alert.severity}
              </span>
              <button
                onClick={() => ackMutation.mutate({ alert_id: alert.id, version: alert.version })}
                disabled={ackMutation.isPending}
                className="text-[11px] font-semibold text-[#4A5568] hover:text-[#1A202C] border border-[#E2E8F0] hover:border-[#CBD5E0] bg-white px-2.5 py-1 rounded-md transition-colors disabled:opacity-50"
              >
                Acknowledge
              </button>
            </div>
            <p className="text-[11px] font-bold text-[#1A202C] mb-1">{alert.title}</p>
            <p className="text-[12px] text-[#2D3748] leading-snug">{alert.message}</p>
            {alert.suggested_action && (
              <p className="mt-2 text-[11px] text-[#4A5568] italic">{'→ ' + alert.suggested_action}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function BarDetailOverlay({ bar, onClose }: Props) {
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

  // Resolve the currently-live event so subcomponents can fetch scoped data
  const mainLiveEventQuery = useLiveEvent()
  const liveEventId = mainLiveEventQuery.data?.id ?? null

  // DASH.6 — fetch per-bar category totals for the Drinks Breakdown section.
  const categoryTotalsQuery = useBarCategoryTotals(liveEventId)
  const barCategoryRow =
    categoryTotalsQuery.data?.bars.find((br) => br.bar_id === b?.id) ?? null

  const revenueEuros = b ? Math.round(b.revenue_cents / 100) : 0

  return (
    <>
      <div
        className={[
          'fixed inset-0 bg-black/50 z-40 transition-opacity duration-300',
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none',
        ].join(' ')}
        onClick={onClose}
      />

      <div
        className={[
          'fixed right-0 top-0 h-full w-[70%] bg-[#F7FAFC] z-50 shadow-2xl flex flex-col',
          'transition-transform duration-300 ease-in-out',
          isOpen ? 'translate-x-0' : 'translate-x-full',
        ].join(' ')}
      >
        {b && (
          <>
            <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-[#E2E8F0] shrink-0 shadow-sm">
              <div className="flex items-center gap-2.5">
                <div className={'w-3 h-3 rounded-full shrink-0 ' + STATUS_DOT[b.status]} />
                <h1 className="text-lg font-bold text-[#1A202C]">{b.name}</h1>
                <span className={'text-xs font-semibold px-2 py-0.5 rounded-full ' + STATUS_LABEL[b.status].cls}>
                  {STATUS_LABEL[b.status].text}
                </span>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="w-8 h-8 flex items-center justify-center rounded-full border border-[#E2E8F0] text-[#4A5568] hover:text-[#1A202C] hover:bg-[#F7FAFC] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </header>

            <div className="flex-1 overflow-y-auto">
              <div className="p-6 space-y-5">

                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Revenue" />
                  <div className="flex items-end gap-3 mb-4">
                    <p className="text-3xl font-bold text-[#1A202C]">
                      &euro;{revenueEuros.toLocaleString()}
                    </p>
                    <span className="text-xs font-semibold bg-[#F7FAFC] text-[#4A5568] border border-[#E2E8F0] px-2 py-1 rounded-full mb-1">
                      Live event
                    </span>
                  </div>
                  <RevenueChart barId={b.id} />
                </section>

                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title={b.bar_type === 'food' ? 'Food Sold' : 'Drinks Breakdown'} />
                  {b.bar_type === 'food' ? (
                    b.food_items.length === 0 ? (
                      <p className="text-sm text-[#A0AEC0] italic">No food sales yet.</p>
                    ) : (
                      <>
                        <div className="flex items-center justify-between mb-3 pb-2 border-b border-[#E2E8F0]">
                          <p className="text-sm text-[#4A5568]">Total items sold</p>
                          <p className="text-xl font-bold text-[#1A202C] tabular-nums">
                            {b.food_items.reduce((s, i) => s + i.sold, 0)}
                          </p>
                        </div>
                        <div className="space-y-1.5">
                          {b.food_items.map((it, idx) => (
                            <div
                              key={it.name}
                              className="flex items-center gap-3 bg-white border border-[#E2E8F0] rounded-lg px-3 py-1.5"
                            >
                              <span className="text-[10px] font-bold text-[#A0AEC0] w-5 text-center">
                                #{idx + 1}
                              </span>
                              <span
                                className="w-2 h-2 rounded-full shrink-0"
                                style={{ backgroundColor: '#558B2F' }}
                              />
                              <span className="flex-1 text-sm text-[#1A202C] truncate" title={it.name}>
                                {it.name}
                              </span>
                              <span className="text-sm font-semibold text-[#1A202C] tabular-nums w-12 text-right">
                                {it.sold}
                              </span>
                            </div>
                          ))}
                        </div>
                      </>
                    )
                  ) : categoryTotalsQuery.isLoading ? (
                    <p className="text-sm text-[#A0AEC0] italic">Loading breakdown...</p>
                  ) : (
                    <>
                      <BarCategoryBreakdown bar={barCategoryRow} bar_type={b.bar_type} />
                      <div className="mt-4">
                        <h3 className="text-[11px] uppercase tracking-wide font-semibold text-[#4A5568] mb-2">
                          Top 5 drinks (by units)
                        </h3>
                        <BarTopDrinks bar={barCategoryRow} bar_type={b.bar_type} />
                      </div>
                    </>
                  )}
                </section>

                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title={'Stock'} />
                  <StockTable barId={b.id} eventId={liveEventId} />
                </section>
                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Alerts" />
                  <AlertsSection barId={b.id} eventId={liveEventId} />
                </section>

                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Chat" />
                  <ChatSection barId={b.id} barName={b.name} />
                </section>

              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
