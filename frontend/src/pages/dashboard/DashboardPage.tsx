/**
 * DashboardPage — Owner-only operational command center.
 *
 * Step 7 wire-up (April 17 2026):
 * - Real data from /bar-stock, /stock-transactions (+ reconciliation), /bars,
 *   /products via hooks in features/dashboard/hooks.ts
 * - Pure transformation layer in features/dashboard/selectors.ts turns raw
 *   API shapes into BarKpi[] consumed by BarCard
 * - Active-event auto-select: dashboard finds the Live event automatically;
 *   ?event_id=... URL override supported for testing against non-live events
 * - Alerts sidebar still mock (no alerts backend yet) — marked TODO
 * - 4 fields on BarCard (burn rate, depletion, staff, last_alert) render as
 *   honest placeholders until v1.1
 *
 * Loading/error pattern follows EventDetailPage: outer wrapper handles
 * states with early returns, inner component receives guaranteed data.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { formatRelativeTime } from '@/lib/utils'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import { usePermissions } from '@/features/auth/usePermissions'
import { BarCard } from '@/features/dashboard/BarCard'
import { EmptyBarCard } from '@/features/dashboard/EmptyBarCard'
import { EventRevenueChart } from '@/features/dashboard/EventRevenueChart' 
import { FreshnessBadge } from '@/features/dashboard/FreshnessBadge'
import { WeatherPill } from '@/features/dashboard/WeatherPill'
import { WristbandActivityFeed } from '@/features/dashboard/WristbandActivityFeed'
import { BarDetailOverlay } from '@/features/dashboard/BarDetailOverlay'
import { BarDashboardView } from '@/features/dashboard/BarDashboardView'
import { SalesBreakdownModal } from '@/features/dashboard/SalesBreakdownModal'
import {
  useAllProducts,
  useBarsForEvent,
  useBarStockForEvent,
  useLiveEvent,
  useReconciliation,
  useTransactionsForEvent,
  useBurnRatesForEvent,
  useEventKpiSummary,
  useMenuPerformance,
  type EventKpiSummaryDTO,
} from '@/features/dashboard/hooks'
import { useBarMappingState } from '@/features/bars/hooks'
import {
  selectBarKpis,
} from '@/features/dashboard/selectors'
import { useAlertsForEvent, useAcknowledgeAlert, useAlertsCountByBar } from '@/features/alerts/useAlerts'
import { useAlertsSocket } from '@/features/alerts/useAlertsSocket'
import type { AlertRow } from '@/features/alerts/useAlerts'
import type { BarKpi, Event } from '@/lib/mockData'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTimer(totalSecs: number) {
  const h = Math.floor(totalSecs / 3600)
  const m = Math.floor((totalSecs % 3600) / 60)
  const s = totalSecs % 60
  return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`
}

function formatCents(cents: number): string {
  return `€${(cents / 100).toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`
}

// ─── Zone A — KPI Strip ───────────────────────────────────────────────────────

function formatEur(eur: string | number): string {
  const n = typeof eur === 'string' ? parseFloat(eur) : eur
  return formatCents(Math.round((Number.isFinite(n) ? n : 0) * 100))
}

interface KpiStripProps {
  kpi: EventKpiSummaryDTO | null
  elapsed: number
  unacknowledgedCount: number
  criticalCount: number
  onAlertsClick: () => void
  onBreakdownClick: () => void
}

function KpiStrip({ kpi, elapsed, unacknowledgedCount, criticalCount, onAlertsClick, onBreakdownClick }: KpiStripProps) {
  const totalRevenue = kpi ? formatEur(kpi.total_revenue_eur) : '\u2014'
  const drinkUnits   = kpi?.drinks.units ?? 0
  const drinkRevenue = kpi ? formatEur(kpi.drinks.revenue_eur) : '\u2014'
  const foodUnits    = kpi?.food.units ?? 0
  const foodNet      = kpi ? formatEur(kpi.food.net_revenue_eur) : '\u2014'
  const foodShare    = kpi?.food.share_pct ?? 100

  return (
    <div className="bg-white border-b border-[#E2E8F0] px-5 py-3 flex items-center gap-0 overflow-x-auto shrink-0 shadow-sm">

      {/* Total Revenue */}
      <div className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0">
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Total Revenue
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none">
            {totalRevenue}
          </p>
        </div>
      </div>

      {/* Drinks - tap for breakdown */}
      <button
        type="button"
        onClick={onBreakdownClick}
        title="View sales breakdown"
        className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0 hover:bg-[#F7FAFC] rounded-lg px-3 py-1 -mx-3 transition-colors text-left cursor-pointer"
      >
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Drinks
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none">
            {drinkUnits}
            <span className="text-sm font-semibold text-[#4A5568] ml-2">{drinkRevenue}</span>
          </p>
        </div>
      </button>

      {/* Food - tap for breakdown */}
      <button
        type="button"
        onClick={onBreakdownClick}
        title="View sales breakdown"
        className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0 hover:bg-[#F7FAFC] rounded-lg px-3 py-1 -mx-3 transition-colors text-left cursor-pointer"
      >
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Food
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none">
            {foodUnits}
            <span className="text-sm font-semibold text-[#4A5568] ml-2">{foodNet}</span>
          </p>
          {foodShare !== 100 && (
            <p className="text-[10px] text-[#4A5568] mt-0.5 whitespace-nowrap">Omar {foodShare}% share</p>
          )}
        </div>
      </button>

      {/* Active Alerts — wired to real backend via useAlertsForEvent */}
      <button
        onClick={onAlertsClick}
        className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0 hover:bg-red-50 rounded-lg px-3 py-1 -mx-3 transition-colors"
      >
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5 text-left">
            Unacknowledged
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none text-left">
            {unacknowledgedCount}
          </p>
        </div>
        {unacknowledgedCount > 0 && (
          <span className="flex items-center gap-1 text-xs font-bold bg-red-100 text-[#E53E3E] border border-red-200 px-2 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E53E3E] animate-pulse" />
            {criticalCount} critical
          </span>
        )}
      </button>

      {/* Time Elapsed */}
      <div className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0">
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Time Elapsed
          </p>
          <p className="text-xl font-bold text-[#1A202C] leading-none font-mono tabular-nums">
            {formatTimer(elapsed)}
          </p>
        </div>
      </div>

    </div>
  )
}

// ─── Zone C — Alert Sidebar (wired to real backend via useAlertsForEvent) ─────

const SEVERITY_CFG = {
  critical: {
    badge:  'bg-red-100 text-[#E53E3E] border border-red-200',
    border: 'border-l-[#E53E3E]',
    barBtn: 'text-[#E53E3E] hover:underline',
  },
  warning: {
    badge:  'bg-yellow-100 text-[#D69E2E] border border-yellow-200',
    border: 'border-l-[#D69E2E]',
    barBtn: 'text-[#D69E2E] hover:underline',
  },
  anomaly: {
    badge:  'bg-orange-100 text-[#E67E22] border border-orange-200',
    border: 'border-l-[#E67E22]',
    barBtn: 'text-[#E67E22] hover:underline',
  },
} as const

interface AlertSidebarAlert {
  id: string
  bar_id: string
  bar_name: string
  severity: 'critical' | 'warning' | 'anomaly'
  alert_type: 'depletion' | 'anomaly' | 'discrepancy' | 'system'
  message: string
  created_at: string
  is_acknowledged: boolean
  // Server-computed alert lifecycle. Distinct from is_acknowledged (which
  // is just a client convenience boolean): 'active' means truly demanding
  // attention; 'resolved'/'expired' should NOT be counted as unacked.
  // Backend ships this field (see features/alerts/useAlerts.ts).
  lifecycle_state: 'active' | 'acknowledged' | 'auto_resolved' | 'expired'
}
interface AlertSidebarProps {
  open: boolean
  onToggle: () => void
  alerts: AlertSidebarAlert[]
  acknowledged: Set<string>
  onAcknowledge: (id: string) => void
}

function AlertSidebar({ open, onToggle, alerts, acknowledged, onAcknowledge }: AlertSidebarProps) {
  const unackedCount = alerts.filter(
    (a) => a.lifecycle_state === 'active' && !acknowledged.has(a.id),
  ).length

  return (
    <div className={[
      'bg-white border-l border-[#E2E8F0] flex flex-col shrink-0 transition-all duration-200',
      open ? 'w-80' : 'w-12',
    ].join(' ')}>

      {/* Header */}
      <div className={[
        'flex items-center border-b border-[#E2E8F0] px-3 py-3 shrink-0',
        open ? 'justify-between' : 'justify-center',
      ].join(' ')}>
        {open && (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-[#1A202C]">Alerts</span>
            {unackedCount > 0 && (
              <span className="flex items-center gap-1 text-xs font-bold bg-red-100 text-[#E53E3E] border border-red-200 px-1.5 py-0.5 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-[#E53E3E] animate-pulse" />
                {unackedCount}
              </span>
            )}
          </div>
        )}
        <button
          onClick={onToggle}
          className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-[#F7FAFC] text-[#4A5568] transition-colors"
          title={open ? 'Collapse alerts' : 'Expand alerts'}
        >
          {open ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <span className="relative">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              {unackedCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 rounded-full bg-[#E53E3E] text-[8px] text-white flex items-center justify-center font-bold">
                  {unackedCount}
                </span>
              )}
            </span>
          )}
        </button>
      </div>


      {/* Alert list — wired to real backend via useAlertsForEvent.
          Filtered to active alerts only: resolved/expired must not show
          an Acknowledge button (they cannot be acknowledged anymore). */}
      {open && (
        <div className="flex-1 overflow-y-auto py-2">
          {alerts
            .filter((alert) => alert.lifecycle_state === 'active')
            .map((alert) => {
            const cfg   = SEVERITY_CFG[alert.severity]
            const acked = acknowledged.has(alert.id)

            return (
              <div
                key={alert.id}
                className={[
                  'mx-2 mb-2 border-l-4 rounded-lg p-3 transition-all',
                  cfg.border,
                  acked
                    ? 'bg-[#F7FAFC] border border-[#E2E8F0] opacity-50'
                    : 'bg-white border border-[#E2E8F0]',
                ].join(' ')}
              >
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-mono font-bold text-[#1A202C]">
                      {formatRelativeTime(alert.created_at)}
                    </span>
                    <span className={`text-xs font-semibold ${cfg.barBtn}`}>
                      {alert.bar_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {alert.alert_type === 'anomaly' && (
                      <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-orange-50 text-[#E67E22] border border-orange-200 uppercase">
                        Anomaly
                      </span>
                    )}
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase ${cfg.badge}`}>
                      {alert.severity}
                    </span>
                  </div>
                </div>

                <p className={`text-xs leading-snug mb-2 ${acked ? 'text-[#4A5568]' : 'text-[#1A202C]'}`}>
                  {alert.message}
                </p>

                {!acked ? (
                  <button
                    onClick={() => onAcknowledge(alert.id)}
                    className="text-[10px] font-semibold text-[#4A5568] border border-[#E2E8F0] bg-[#F7FAFC] hover:bg-[#EDF2F7] px-2.5 py-1 rounded-md transition-colors"
                  >
                    Acknowledge
                  </button>
                ) : (
                  <span className="text-[10px] text-[#4A5568] italic">Acknowledged</span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Page wrapper: handles loading/error/no-event states ─────────────────────

const START_ELAPSED = 2 * 3600 + 35 * 60  // 2h 35m (placeholder — real timer comes from event.started_at in v1.1)

export default function DashboardPage() {
  const navigate         = useNavigate()
  const { user }         = useAuth()
  const perms            = usePermissions()
  const [searchParams]   = useSearchParams()

  // Role-aware branch: Owner sees the multi-bar overview below; Manager
  // and Bartender get their per-bar 'My Bar' view. Warehouse keepers
  // never reach this page (route guard redirects them to /warehouse).
  // Spec: docs/bar-dashboard-spec.md S3.
  const role = user?.role
  if (role === 'manager' || role === 'bartender') {
    return <BarDashboardView role={role} />
  }
  // Belt-and-suspenders for any unexpected role: route guard already
  // gates this page, so we shouldn't reach here. If we do, redirect home.
  if (!perms.canViewAllBars) {
    navigate('/', { replace: true })
    return null
  }

  // ── Active-event resolution: ?event_id=... overrides Live auto-select ──
  const urlEventId = searchParams.get('event_id')
  const liveEventQuery = useLiveEvent()

  // If URL has ?event_id, use it. Otherwise wait for liveEventQuery.
  const eventId = urlEventId ?? liveEventQuery.data?.id ?? null

  // ── Loading state: still resolving which event to show ──
  if (!urlEventId && liveEventQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[#4A5568]">
        Finding the active event…
      </div>
    )
  }

  // ── No event found ──
  if (!eventId) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 p-8 text-center">
        <p className="text-sm text-[#4A5568] max-w-md">
          No Live event in progress. The dashboard shows real-time metrics
          for the currently-active event. Start an event from the Events
          page, or pass <code className="font-mono bg-[#F7FAFC] px-1 py-0.5 rounded">?event_id=…</code> in the URL to view a specific event.
        </p>
        <button
          onClick={() => navigate('/events')}
          className="text-xs font-medium text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#F0F7FF] transition-colors"
        >
          Go to Events
        </button>
      </div>
    )
  }

  // ── Happy path: we have an eventId, render the live dashboard ──
  const fallbackEvent: Event | null = liveEventQuery.data ?? null
  return <DashboardContent eventId={eventId} liveEvent={fallbackEvent} />
}

// ─── Content: assumes eventId is resolved ────────────────────────────────────

interface DashboardContentProps {
  eventId:   string
  liveEvent: Event | null
}

function DashboardContent({ eventId, liveEvent }: DashboardContentProps) {
  const navigate  = useNavigate()
  const alertsRef = useRef<HTMLDivElement>(null)

  // ── Data hooks (all gated on eventId via `enabled` internally) ──
  const barsQuery          = useBarsForEvent(eventId)
  const mappingStateQuery  = useBarMappingState(eventId)
  const barStockQuery      = useBarStockForEvent(eventId)
  const transactionsQuery  = useTransactionsForEvent(eventId)
  const burnRatesQuery     = useBurnRatesForEvent(eventId)
  const kpiQuery           = useEventKpiSummary(eventId)
  const menuQuery          = useMenuPerformance(eventId)
  const productsQuery      = useAllProducts()
  const alertsQuery        = useAlertsForEvent(eventId, { onlyActive: false })
  const alertCountsByBarQuery = useAlertsCountByBar(eventId)

  // Time references for the multi-line charts.
  // Computed ONCE per render so all 22 bar cards + the event chart
  // share the same buckets. liveEvent.started_at may be null for
  // events that haven\'t started — fall back to "1h ago" so charts
  // render an empty timeline instead of crashing.
  const nowMs = Date.now()
  const eventStartMs = liveEvent?.started_at
    ? new Date(liveEvent.started_at).getTime()
    : nowMs - 3600_000
  // Live push: keeps all alerts queries fresh via WebSocket invalidation.
  // If the socket disconnects, the 10s polling fallback inside the query
  // hooks still keeps the UI correct — belt AND suspenders.
  useAlertsSocket(eventId)
  const acknowledgeMutation = useAcknowledgeAlert()
  // Adapter: map real AlertRow[] -> legacy Alert shape consumed by AlertSidebar
  // and the KpiStrip. Derives bar_name from context_json; is_acknowledged from
  // acknowledged_at; clamps 'info' severity to 'warning' for display only.
  const alerts = (alertsQuery.data?.items ?? []).map((row: AlertRow) => ({
    id:              row.id,
    event_id:        row.event_id,
    bar_id:          row.bar_id,
    bar_name:        (row.context_json?.bar_name as string) ?? 'Unknown bar',
    severity:        (row.severity === 'info' ? 'warning' : row.severity) as 'critical' | 'warning' | 'anomaly',
    alert_type:      row.alert_type,
    message:         row.message,
    created_at:      row.created_at,
    is_acknowledged: row.acknowledged_at !== null,
    // carry the real version for the ack mutation
    _version:        row.version,
    // carry lifecycle_state so the filter can distinguish active from
    // resolved/expired alerts (prevents counting auto-resolved as unacked)
    lifecycle_state: row.lifecycle_state,
  }))
  // reconciliation is used by BarDetailOverlay in v1.1 — prefetched here so
  // it's warm when the overlay opens
  useReconciliation(eventId)

  // ── UI state ──
  const [elapsed,     setElapsed]     = useState(START_ELAPSED)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [breakdownOpen, setBreakdownOpen] = useState(false)
  const [selectedBar, setSelectedBar] = useState<BarKpi | null>(null)
  // Acknowledged set derived from server data — not local state. The source of
  // truth is alerts[i].acknowledged_at on the server; this Set is just a fast
  // lookup by id for the presentation components.
  const acknowledged = new Set(alerts.filter((a) => a.is_acknowledged).map((a) => a.id))

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const handleAcknowledge = useCallback((id: string) => {
    // Find the current version to pass to the optimistic-lock mutation.
    const target = alerts.find((a) => a.id === id)
    if (!target) return
    acknowledgeMutation.mutate({ alert_id: id, version: target._version })
  }, [alerts, acknowledgeMutation])

  function handleAlertsClick() {
    setSidebarOpen(true)
    alertsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // ── Loading guard: wait for all 4 queries to have data ──
  const isAnyLoading =
    barsQuery.isLoading ||
    barStockQuery.isLoading ||
    transactionsQuery.isLoading ||
    productsQuery.isLoading

  if (isAnyLoading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[#4A5568]">
        Loading dashboard…
      </div>
    )
  }

  // ── Error guard ──
  const anyError =
    barsQuery.error ||
    barStockQuery.error ||
    transactionsQuery.error ||
    productsQuery.error

  if (anyError) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-sm">
        <p className="text-[#E53E3E]">Failed to load dashboard data. Check the backend is reachable.</p>
        <button
          onClick={() => {
            barsQuery.refetch()
            barStockQuery.refetch()
            transactionsQuery.refetch()
            productsQuery.refetch()
          }}
          className="px-4 py-2 rounded-lg font-semibold text-white text-xs bg-[#3182CE] hover:bg-[#2B6CB0] transition-colors"
        >
          Retry now
        </button>
        <p className="text-[10px] text-[#A0AEC0]">Reconnecting automatically every 15s…</p>
      </div>
    )
  }

  // ── All data arrived — compute the BarKpi view-model ──
  const bars         = barsQuery.data ?? []
  const barStock     = barStockQuery.data ?? []
  const transactions = transactionsQuery.data ?? []
  const products     = productsQuery.data ?? []

  const barKpis: BarKpi[] = selectBarKpis({ bars, barStock, transactions, products, burnRates: burnRatesQuery.data ?? [] })

  // Partition by mapping state. Live = mapped + stubs (rendered as BarCards
  // in the main grid). Empty = wizard-defined bars with no shop_id yet
  // (rendered as muted EmptyBarCards below the grid). If mapping-state
  // hasn't loaded yet, all bars render as live (pre-Phase-1 behavior).
  const emptyBars          = mappingStateQuery.data?.empty_bars ?? []
  const emptyBarIdSet      = new Set(emptyBars.map((b) => b.id))
  const liveKpis: BarKpi[] = mappingStateQuery.data
    ? barKpis.filter((k) => !emptyBarIdSet.has(k.id))
    : barKpis

  const unacknowledgedCount = alerts.filter(
    (a) => a.lifecycle_state === 'active' && !acknowledged.has(a.id),
  ).length

  const eventName = liveEvent?.name ?? `Event ${eventId.slice(0, 8)}`
  const eventStatusLabel = liveEvent?.status === 'live' ? 'Live' : liveEvent?.status ?? 'Preview'

  return (
    <div className="flex h-full overflow-hidden">

      {/* Left column — Zone A + Zone B (75%) */}
      <div className="flex flex-col flex-1 overflow-hidden">

        {/* Zone A — KPI Strip */}
        <KpiStrip
          kpi={kpiQuery.data ?? null}
          elapsed={elapsed}
          unacknowledgedCount={unacknowledgedCount}
          criticalCount={alerts.filter((a) => a.severity === 'critical' && a.lifecycle_state === 'active' && !acknowledged.has(a.id)).length}
          onAlertsClick={handleAlertsClick}
          onBreakdownClick={() => setBreakdownOpen(true)}
        />
        <SalesBreakdownModal menu={menuQuery.data ?? null} open={breakdownOpen} onClose={() => setBreakdownOpen(false)} />

        {/* Zone B — Bar card grid */}
        <main className="flex-1 overflow-y-auto p-5 bg-[#F7FAFC]">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-lg font-bold text-[#1A202C]">Bar Performance</h1>
                <FreshnessBadge />
                <WeatherPill eventId={eventId} />
              </div>
              <p className="text-xs text-[#4A5568] mt-0.5">
                {eventName} · {eventStatusLabel} · {barKpis.length} {barKpis.length === 1 ? 'bar' : 'bars'}
              </p>
            </div>
            <button
              onClick={() => navigate('/alerts')}
              className="text-xs font-medium text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#F0F7FF] transition-colors"
            >
              View All Alerts
            </button>
          </div>

          {barKpis.length === 0 ? (
            <div className="bg-white rounded-xl p-12 text-center text-sm text-[#4A5568]">
              No bars set up for this event yet. Add bars from the event detail page.
            </div>
          ) : (
            <>
              {barKpis.length > 0 && barKpis.filter((b) => b.revenue_cents === 0 && b.drinks_sold === 0).length / barKpis.length >= 0.8 && (
                <div className="bg-[#F0F7FF] border border-[#1E5A8D]/20 rounded-xl px-4 py-3 mb-4 text-xs text-[#1E5A8D] flex items-start gap-2">
                  <svg className="w-4 h-4 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />
                  </svg>
                  <span>
                    Most bars are still awaiting their first order. Cards populate as transactions stream in from Slesh POS — bars with activity are shown with live numbers below.
                  </span>
                </div>
              )}
              {/* Big event-total revenue chart — Actual (live) vs ML Predicted.
                  Locked May 27 2026: replaces the per-bar chart in the
                  overlay. Spans full width of the grid above so it reads
                  as ~2 bar cards wide. ML Predicted line is null until
                  MLPredictor lands (Phase 2 resumption). */}
              <div className="mb-4">
                <EventRevenueChart
                  transactions={transactionsQuery.data ?? []}
                  eventStartMs={eventStartMs}
                  nowMs={nowMs}
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {liveKpis.map((kpi) => (
                  <BarCard
                    key={kpi.id}
                    bar={kpi}
                    criticalAlertCount={alertCountsByBarQuery.data?.get(kpi.id)?.critical ?? 0}
                    onClick={(id) => setSelectedBar(liveKpis.find((b) => b.id === id) ?? null)}
                    transactions={transactionsQuery.data ?? []}
                    products={productsQuery.data ?? []}
                    eventStartMs={eventStartMs}
                    nowMs={nowMs}
                  />
                ))}
              </div>
              {emptyBars.length > 0 && (
                <div className="mt-6">
                  <h3 className="text-xs font-semibold text-[#4A5568] uppercase tracking-wide mb-3">
                    Awaiting activity · {emptyBars.length}
                  </h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                    {emptyBars.map((bar) => (
                      <EmptyBarCard key={bar.id} bar={bar} />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {/* Zone C — Right column: alerts on top, wristband activity below */}
      <div ref={alertsRef} className="flex-none flex flex-col overflow-y-auto max-h-screen">
        <AlertSidebar
          open={sidebarOpen}
          onToggle={() => setSidebarOpen((o) => !o)}
          alerts={alerts}
          acknowledged={acknowledged}
          onAcknowledge={handleAcknowledge}
        />
        {sidebarOpen && (
          <div className="border-l border-[#E2E8F0] bg-white p-3 w-80">
            <WristbandActivityFeed eventId={eventId} limit={25} />
          </div>
        )}
      </div>

      {/* Bar detail overlay — sits above everything */}
      {/* NOTE: BarDetailOverlay still expects the OLD Bar type from mockData.
          Casting via `as never` is a temporary bridge — overlay wiring is Step 7b. */}
      <BarDetailOverlay
        bar={selectedBar}
        onClose={() => setSelectedBar(null)}
      />
    </div>
  )
}
