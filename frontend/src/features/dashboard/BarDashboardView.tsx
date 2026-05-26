/**
 * BarDashboardView — Manager + Bartender role-aware dashboard.
 *
 * Spec: docs/bar-dashboard-spec.md S3 through S7.
 *
 * Role gating per spec S5.3:
 *   Manager   = sees + can action everything (acknowledge alerts, restock)
 *   Bartender = sees same data, NO action buttons (read-only)
 *
 * Data flow:
 *   Backend bar-scoping (sub-patch 3b.1) means we don't pass bar_id from
 *   the frontend — the server auto-filters using the JWT's assignedBarId.
 *   The hooks below return only this user's bar's data.
 *
 * Sub-patch 3b.4: 4 KPI tiles + alerts panel + transactions table wired
 * to real data. Bar chat panel + Restock button arrive in 3b.5.
 * WebSocket sync in 3b.6.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import {
  useAllProducts,
  useBarsForEvent,
  useBarStockForEvent,
  useLiveEvent,
  useTransactionsForEvent,
} from '@/features/dashboard/hooks'
import {
  useAcknowledgeAlert,
  useAlertsForEvent,
  type AlertRow,
} from '@/features/alerts/useAlerts'
import {
  useChannels,
  useChannelMessages,
  usePostMessage,
} from '@/features/chat/useChat'
import { useChatSocket } from '@/features/chat/useChatSocket'
import { useDashboardSocket } from '@/features/dashboard/useDashboardSocket'
import { useState } from 'react'

// ─── Types ───────────────────────────────────────────────────────────

export type DashboardRole = 'manager' | 'bartender'

interface BarDashboardViewProps {
  role: DashboardRole
}

// ─── Helpers ─────────────────────────────────────────────────────────

function fmtEur(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return '€0'
  return new Intl.NumberFormat('it-IT', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(cents / 100)
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}h ago`
  return new Date(iso).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── Live-sync indicator ─────────────────────────────────────────────

function LiveSyncIndicator({ isConnected }: { isConnected: boolean }) {
  // Wired to real WebSocket connection state (3b.6).
  // Green = connected, frames flowing live.
  // Orange = not connected; the 10s polling fallback carries data
  //          freshness silently — user is never stranded.
  const dotColor = isConnected ? '#10B981' : '#DD6B20'
  const label = isConnected ? 'live' : 'polling'
  return (
    <div className="flex items-center gap-2 text-xs text-[#718096]">
      <span
        className="w-2 h-2 rounded-full"
        style={{ backgroundColor: dotColor }}
        aria-label={isConnected ? 'Live, real-time updates' : 'Polling fallback active'}
      />
      <span>{label}</span>
    </div>
  )
}

// ─── KPI tiles ───────────────────────────────────────────────────────

interface KpiTileProps {
  label: string
  value: string
  hint?: string
  accent?: 'default' | 'warning' | 'danger' | 'success'
}

function KpiTile({ label, value, hint, accent = 'default' }: KpiTileProps) {
  const accentColor =
    accent === 'danger'  ? '#E53E3E' :
    accent === 'warning' ? '#DD6B20' :
    accent === 'success' ? '#10B981' :
                            '#1E5A8D'
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm flex flex-col">
      <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-1">
        {label}
      </p>
      <p className="text-2xl font-bold leading-tight" style={{ color: accentColor }}>
        {value}
      </p>
      {hint && <p className="text-xs text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}

// ─── Alerts panel ────────────────────────────────────────────────────

const SEVERITY_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  critical: { bg: '#FEE2E2', color: '#991B1B', label: 'CRITICAL' },
  warning:  { bg: '#FEF3C7', color: '#92400E', label: 'WARNING' },
  anomaly:  { bg: '#FECACA', color: '#7F1D1D', label: 'ANOMALY' },
  info:     { bg: '#DBEAFE', color: '#1E40AF', label: 'INFO' },
}

function AlertRowView({
  alert,
  canAct,
  onAcknowledge,
}: {
  alert: AlertRow
  canAct: boolean
  onAcknowledge: () => void
}) {
  const style =
    SEVERITY_STYLES[alert.severity as string] ?? SEVERITY_STYLES.info
  const isAcked = alert.acknowledged_at !== null

  return (
    <div className="border-b border-[#EDF2F7] last:border-b-0 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span
              className="inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest rounded-full"
              style={{ backgroundColor: style.bg, color: style.color }}
            >
              {style.label}
            </span>
            <span className="text-xs text-[#718096]">
              {fmtRelative(alert.created_at)}
            </span>
            {isAcked && (
              <span className="text-[10px] font-semibold text-[#059669]">
                ✓ acknowledged
              </span>
            )}
          </div>
          <p className="text-sm text-[#1A202C]">{alert.message}</p>
        </div>
        {canAct && !isAcked && (
          <button
            onClick={onAcknowledge}
            className="text-xs font-semibold text-[#4A5568] border border-[#E2E8F0] hover:bg-[#EDF2F7] bg-white px-3 py-1 rounded-lg whitespace-nowrap"
          >
            Acknowledge
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Transactions table ──────────────────────────────────────────────

function TransactionsTable({
  transactions,
  productNamesById,
}: {
  transactions: Array<{
    id: string
    created_at: string
    product_id: string
    qty: string | number
    price_cents: number | null
    source: string
  }>
  productNamesById: Map<string, string>
}) {
  if (transactions.length === 0) {
    return (
      <div className="py-8 text-center">
        <p className="text-sm text-[#A0AEC0] italic">
          No sales yet tonight. Transactions will appear here as they happen.
        </p>
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest border-b border-[#EDF2F7]">
            <th className="text-left py-2 px-2">Time</th>
            <th className="text-left py-2 px-2">Product</th>
            <th className="text-right py-2 px-2">Qty</th>
            <th className="text-left py-2 px-2">Source</th>
            <th className="text-right py-2 px-2">Total</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((tx) => {
            const total =
              tx.price_cents !== null
                ? Number(tx.qty) * tx.price_cents
                : null
            return (
              <tr key={tx.id} className="border-b border-[#F1F5F9] last:border-0">
                <td className="py-2 px-2 text-sm text-[#4A5568]">
                  {fmtTime(tx.created_at)}
                </td>
                <td className="py-2 px-2 text-sm text-[#1A202C] font-medium">
                  {productNamesById.get(tx.product_id) ?? `${tx.product_id.slice(0, 8)}…`}
                </td>
                <td className="py-2 px-2 text-right text-sm">{tx.qty}</td>
                <td className="py-2 px-2 text-xs text-[#718096]">{tx.source}</td>
                <td className="py-2 px-2 text-right text-sm font-semibold">
                  {fmtEur(total)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── Empty / edge states ─────────────────────────────────────────────

function NoBarAssignedBanner() {
  return (
    <div className="bg-[#FEF3C7] border border-[#F59E0B] rounded-xl p-4 max-w-xl mx-auto mt-8">
      <p className="text-sm font-semibold text-[#92400E] mb-1">
        Your account isn't assigned to a bar
      </p>
      <p className="text-xs text-[#92400E]">
        Contact your tenant admin to get assigned to a bar so this dashboard
        can show your data.
      </p>
    </div>
  )
}

function NoLiveEventState() {
  return (
    <div className="max-w-xl mx-auto mt-12 text-center">
      <p className="text-4xl mb-3">��</p>
      <p className="text-sm font-semibold text-[#1A202C] mb-1">
        No Live event in progress
      </p>
      <p className="text-xs text-[#718096] max-w-md mx-auto">
        Your bar dashboard activates when an event is live. Once an event
        is started, this page will show your bar's stock, alerts, recent
        sales, and chat — all updating in real time.
      </p>
    </div>
  )
}

// ─── Bar chat panel ──────────────────────────────────────────────────

interface BarChatPanelProps {
  role: DashboardRole
  assignedBarId: string
  barName: string
  atRiskCount: number
}

function BarChatPanel({
  role,
  assignedBarId,
  barName,
  atRiskCount,
}: BarChatPanelProps) {
  const channelsQuery = useChannels()
  const { user } = useAuth()

  // Find this bar's channel. Channels with channel_type='bar' and the
  // matching bar_id are auto-created when the bar is created.
  const channel = (channelsQuery.data ?? []).find(
    (c) => c.channel_type === 'bar' && c.bar_id === assignedBarId,
  )
  const channelId = channel?.id ?? null

  const messagesQuery = useChannelMessages(channelId, 5)
  const postMessage = usePostMessage(channelId ?? '')

  // Subscribe to live chat updates so messages sent from /chat (or another
  // tab) flow back into this panel without a manual refresh. Mirrors the
  // ChatPage usage but scoped to just this bar's channel.
  // Closes test failures B4 and B7 from the 2026-04-28 automated test run.
  useChatSocket({
    activeChannelId: channelId,
    currentUserId: user?.id ?? '',
    allChannelIds: channelId ? [channelId] : [],
  })

  const [draft, setDraft] = useState('')

  const canWrite = role === 'manager'
  const messages = messagesQuery.data ?? []

  function handleSend() {
    if (!channelId || !draft.trim()) return
    postMessage.mutate(
      { body: draft.trim() },
      { onSuccess: () => setDraft('') },
    )
  }

  function handleRestockRequest() {
    if (!channelId) return
    const lowItems =
      atRiskCount > 0
        ? `${atRiskCount} item${atRiskCount === 1 ? '' : 's'} at risk`
        : 'stock running low'
    const body = `@Owner — Bar ${barName} needs restock. Status: ${lowItems}.`
    postMessage.mutate({ body })
  }

  // Empty / loading states
  if (channelsQuery.isLoading) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm flex flex-col min-h-[240px]">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
          Bar Chat
        </p>
        <p className="text-xs text-[#A0AEC0] flex-1 flex items-center justify-center">
          Loading chat…
        </p>
      </div>
    )
  }

  if (!channel) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm flex flex-col min-h-[240px]">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
          Bar Chat
        </p>
        <p className="text-xs text-[#A0AEC0] italic flex-1 flex items-center justify-center text-center">
          Chat not yet configured for this bar.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm flex flex-col min-h-[240px]">
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
          Bar Chat
        </p>
        <p className="text-[10px] text-[#A0AEC0]">{channel.name}</p>
      </div>

      {/* Recent messages */}
      <div className="flex-1 overflow-y-auto mb-2 space-y-2 max-h-[160px]">
        {messages.length === 0 ? (
          <p className="text-xs text-[#A0AEC0] italic text-center py-4">
            No messages yet. {canWrite ? 'Start the conversation below.' : ''}
          </p>
        ) : (
          messages.slice(0, 5).map((m) => (
            <div key={m.id} className="text-xs">
              <span className="font-semibold text-[#1A202C]">
                {m.sender_name ?? 'Unknown'}
              </span>
              <span className="text-[#A0AEC0] ml-2">
                {fmtTime(m.created_at)}
              </span>
              <p className="text-[#4A5568] mt-0.5">{m.body}</p>
            </div>
          ))
        )}
      </div>

      {/* Manager-only input + actions */}
      {canWrite && (
        <div className="border-t border-[#EDF2F7] pt-2 space-y-2">
          <div className="flex gap-1.5">
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="Type a message…"
              className="flex-1 px-2 py-1 text-xs border border-[#E2E8F0] rounded-md focus:border-[#1E5A8D] focus:outline-none"
              disabled={postMessage.isPending}
            />
            <button
              onClick={handleSend}
              disabled={!draft.trim() || postMessage.isPending}
              className="text-xs px-3 py-1 rounded-md bg-[#1E5A8D] text-white hover:bg-[#174a78] disabled:opacity-50"
            >
              Send
            </button>
          </div>
          <button
            onClick={handleRestockRequest}
            disabled={postMessage.isPending}
            className="w-full text-xs px-3 py-1.5 rounded-md border border-[#DD6B20] text-[#DD6B20] hover:bg-[#FFF7ED] disabled:opacity-50"
          >
            + Request Restock
          </button>
        </div>
      )}

      <Link
        to={`/chat?channel=${channel.id}`}
        className="text-xs text-[#1E5A8D] hover:text-[#2C7AA6] underline mt-2 self-end"
      >
        Open full chat →
      </Link>
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────

export function BarDashboardView({ role }: BarDashboardViewProps) {
  const { user } = useAuth()
  const liveEventQuery = useLiveEvent()

  const assignedBarId = user?.assignedBarId ?? null
  const eventId = liveEventQuery.data?.id ?? null

  // Hooks always called (Rules of Hooks); they no-op when eventId is null.
  const barStockQuery = useBarStockForEvent(eventId)
  const transactionsQuery = useTransactionsForEvent(eventId)
  const productsQuery = useAllProducts()
  const alertsQuery = useAlertsForEvent(eventId, { onlyActive: false })
  const barsQuery = useBarsForEvent(eventId)
  const acknowledge = useAcknowledgeAlert()

  // Real-time push for the dashboard. Sub-patch 3b.6: opens one WS per
  // mount, listens for stock:* + event:* frames, invalidates dashboard
  // + alerts caches on any update so KPI tiles, alerts panel, and the
  // transactions table react in <200ms.
  const { isConnected: wsConnected } = useDashboardSocket(eventId)

  // Bar name lookup (the GET /bars endpoint already returns this user's bar
  // because they're scoped to it; for v1 we just match by id).
  const barName = useMemo(() => {
    if (!assignedBarId || !barsQuery.data) return 'My Bar'
    const found = barsQuery.data.find((b) => b.id === assignedBarId)
    return found?.name ?? 'My Bar'
  }, [assignedBarId, barsQuery.data])

  // ── Derived KPIs ───────────────────────────────────────────────────

  const stockHealth = useMemo(() => {
    const rows = barStockQuery.data ?? []
    const totalAllocated = rows.reduce((s, r) => s + Number(r.allocated_qty || 0), 0)
    const totalCurrent = rows.reduce((s, r) => s + Number(r.current_qty || 0), 0)
    const atRisk = rows.filter(
      (r) => Number(r.current_qty) <= 0.2 * Number(r.allocated_qty || 1),
    ).length
    const pct = totalAllocated > 0 ? Math.round((totalCurrent / totalAllocated) * 100) : 0
    return {
      totalProducts: rows.length,
      totalCurrent,
      totalAllocated,
      atRisk,
      pct,
    }
  }, [barStockQuery.data])

  // Revenue = sum(qty * price_cents) over revenue-producing transactions.
  // Matches the reports module aggregator pattern: only slesh_pos +
  // manual_bartender count as sales; reconciliation/adjustment do not.
  const revenue = useMemo(() => {
    const txs = transactionsQuery.data ?? []
    const REVENUE_SOURCES = new Set(['slesh_pos', 'manual_bartender'])
    let cents = 0
    for (const tx of txs) {
      if (!REVENUE_SOURCES.has(String(tx.source))) continue
      if (tx.price_cents === null) continue
      cents += Number(tx.qty) * tx.price_cents
    }
    return Math.round(cents)
  }, [transactionsQuery.data])

  const alertsByBar = useMemo(() => {
    const items = alertsQuery.data?.items ?? []
    if (assignedBarId === null) return items
    return items.filter((a) => a.bar_id === assignedBarId)
  }, [alertsQuery.data, assignedBarId])

  const unackedAlerts = alertsByBar.filter((a) => a.lifecycle_state === 'active')
  const criticalAlerts = unackedAlerts.filter((a) => a.severity === 'critical')

  const recentTransactions = useMemo(() => {
    const items = transactionsQuery.data ?? []
    return items.slice(0, 5)
  }, [transactionsQuery.data])

  // Map product_id -> name for the transactions table. Without this lookup
  // the table renders truncated UUIDs (test failure A12, 2026-04-28).
  const productNamesById = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of productsQuery.data ?? []) {
      m.set(p.id, p.name)
    }
    return m
  }, [productsQuery.data])

  // ── Edge cases ─────────────────────────────────────────────────────

  if (assignedBarId === null) {
    return <NoBarAssignedBanner />
  }

  if (liveEventQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[#4A5568] py-12">
        Finding the active event…
      </div>
    )
  }

  if (!eventId) {
    return <NoLiveEventState />
  }

  // ── Render ─────────────────────────────────────────────────────────

  const canAct = role === 'manager'

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">{barName}</h1>
          <p className="text-sm text-[#718096] mt-1">
            Sundance 2026 · Live event in progress
          </p>
        </div>
        <LiveSyncIndicator isConnected={wsConnected} />
      </div>

      {/* 4 KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <KpiTile
          label="Stock Health"
          value={`${stockHealth.pct}%`}
          hint={`${stockHealth.totalCurrent} units · ${stockHealth.atRisk} at risk`}
          accent={
            stockHealth.pct < 20 ? 'danger' :
            stockHealth.pct < 50 ? 'warning' :
            'success'
          }
        />
        <KpiTile
          label="Revenue Tonight"
          value={fmtEur(revenue)}
          hint={revenue > 0 ? 'live' : 'no sales yet'}
        />
        <KpiTile
          label="Unacknowledged"
          value={String(unackedAlerts.length)}
          hint={
            criticalAlerts.length > 0
              ? `${criticalAlerts.length} critical`
              : unackedAlerts.length === 0
                ? 'all clear'
                : 'unresolved'
          }
          accent={criticalAlerts.length > 0 ? 'danger' : 'default'}
        />
        <KpiTile
          label="Last 5 Transactions"
          value={String(recentTransactions.length)}
          hint={transactionsQuery.data ? `of ${transactionsQuery.data.length} today` : '—'}
        />
      </div>

      {/* Alerts panel + Chat panel placeholder */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="lg:col-span-2 bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm">
          <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
            Unacknowledged
          </p>
          {alertsQuery.isLoading && (
            <p className="text-xs text-[#A0AEC0] py-4">Loading alerts…</p>
          )}
          {!alertsQuery.isLoading && alertsByBar.length === 0 && (
            <p className="text-xs text-[#A0AEC0] italic py-4 text-center">
              All quiet at your bar. Stockouts, depletion warnings, and anomaly
              flags will appear here.
            </p>
          )}
          {alertsByBar.slice(0, 8).map((alert) => (
            <AlertRowView
              key={alert.id}
              alert={alert}
              canAct={canAct}
              onAcknowledge={() =>
                acknowledge.mutate({ alert_id: alert.id, version: alert.version })
              }
            />
          ))}
        </div>

        {/* Chat panel — real bar chat (3b.5) */}
        <BarChatPanel
          role={role}
          assignedBarId={assignedBarId}
          barName={barName}
          atRiskCount={stockHealth.atRisk}
        />
      </div>

      {/* Transactions table */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-sm mb-6">
        <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest mb-3">
          Last 5 Transactions
        </p>
        {transactionsQuery.isLoading && (
          <p className="text-xs text-[#A0AEC0] py-4">Loading transactions…</p>
        )}
        {!transactionsQuery.isLoading && (
          <TransactionsTable transactions={recentTransactions} productNamesById={productNamesById} />
        )}
      </div>

      {/* Footer links */}
      <div className="flex flex-wrap gap-3 text-xs">
        <Link
          to="/inventory"
          className="text-[#1E5A8D] hover:text-[#2C7AA6] underline"
        >
          → Full inventory list
        </Link>
        {role === 'manager' && (
          <Link
            to="/alerts"
            className="text-[#1E5A8D] hover:text-[#2C7AA6] underline"
          >
            → Full alerts page
          </Link>
        )}
        <Link
          to="/chat"
          className="text-[#1E5A8D] hover:text-[#2C7AA6] underline"
        >
          → Full chat
        </Link>
      </div>
    </div>
  )
}
