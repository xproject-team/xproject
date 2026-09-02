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
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { formatRelativeTime } from '@/lib/utils'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/useAuth'
import { usePermissions } from '@/features/auth/usePermissions'
import { BarCard } from '@/features/dashboard/BarCard'
import { EmptyBarCard } from '@/features/dashboard/EmptyBarCard'
import { RechargeDeskCard } from '@/features/dashboard/RechargeDeskCard'
import { SeasonIdleView } from '@/features/dashboard/SeasonIdleView'
import { useBarAllocations } from '@/features/event_storage/hooks'
import { useEvent } from '@/features/events/hooks'
import { EventRevenueChart } from '@/features/dashboard/EventRevenueChart'
import { RevenueForecastPanel } from '@/features/dashboard/RevenueForecastPanel'
import { useRevenueForecast } from '@/features/predictions/useRevenueForecast'
import { CustomerIntelligencePanel } from '@/features/dashboard/CustomerIntelligencePanel'
import { useCustomerIntelligence } from '@/features/customer-intelligence/useCustomerIntelligence'
import { FreshnessBadge } from '@/features/dashboard/FreshnessBadge'
import { WeatherPill } from '@/features/dashboard/WeatherPill'
import { WristbandActivityFeed } from '@/features/dashboard/WristbandActivityFeed'
import { BarDetailOverlay } from '@/features/dashboard/BarDetailOverlay'
import { BarDashboardView } from '@/features/dashboard/BarDashboardView'
import { SalesBreakdownModal } from '@/features/dashboard/SalesBreakdownModal'
import { RevenueBreakdownModal } from '@/features/dashboard/RevenueBreakdownModal'
import {
  useAllProducts,
  useBarsForEvent,
  useBarStockForEvent,
  useLiveEvent,
  useReconciliation,
  useTransactionsForEvent,
  useBurnRatesForEvent,
  useEventKpiSummary,
  useEventRevenueBreakdown,
  useMenuPerformance,
  type EventKpiSummaryDTO,
} from '@/features/dashboard/hooks'
import { useBarMappingState, useMergeBars } from '@/features/bars/hooks'
import { useBarSupplierStock } from '@/features/dashboard/hooks'
import {
  selectBarKpis,
} from '@/features/dashboard/selectors'
import { useAlertsForEvent, useAcknowledgeAlert, useAlertsCountByBar } from '@/features/alerts/useAlerts'
import { useAlertsSocket } from '@/features/alerts/useAlertsSocket'
import type { AlertRow } from '@/features/alerts/useAlerts'
import { MapShopToBarModal } from '@/features/alerts/MapShopToBarModal'
import type { BarKpi, Event } from '@/lib/mockData'
import { MetricTile, Badge, Button, EmptyState, type VeraRole } from '@/design-system/components'
import '@/design-system/components/components.css'

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
  isLive: boolean
  onAlertsClick: () => void
  onBreakdownClick: () => void
}

function KpiStrip({ kpi, elapsed, unacknowledgedCount, criticalCount, isLive, onAlertsClick, onBreakdownClick }: KpiStripProps) {
  const totalRevenue = kpi ? formatEur(kpi.total_revenue_eur) : '\u2014'
  const drinkUnits   = kpi?.drinks.units ?? 0
  const drinkRevenue = kpi ? formatEur(kpi.drinks.revenue_eur) : '\u2014'
  const foodUnits    = kpi?.food.units ?? 0
  const foodNet      = kpi ? formatEur(kpi.food.net_revenue_eur) : '\u2014'
  const foodShare    = kpi?.food.share_pct ?? 100
  // Already included in totalRevenue \u2014 surfaced explicitly rather than
  // left invisible inside the total (F-01: this used to be silently
  // dropped from the total entirely; now it's visible instead).
  const unmappedRevenue = kpi && Number(kpi.unmapped_revenue_eur) > 0
    ? formatEur(kpi.unmapped_revenue_eur)
    : null

  const unackAccent: VeraRole = criticalCount > 0 ? 'pink' : 'amber'

  return (
    <div className="grid grid-cols-5 gap-3 px-5 py-3 shrink-0">
      <MetricTile label="Total Revenue" value={totalRevenue} accent="cyan">
        {unmappedRevenue && (
          <span className="text-[10px] block whitespace-nowrap" style={{ color: 'var(--v-amber)' }}>
            {unmappedRevenue} not yet assigned to a bar
          </span>
        )}
      </MetricTile>

      <MetricTile label="Drinks" value={String(drinkUnits)} accent="cyan" onClick={onBreakdownClick}>
        <span className="text-xs mt-0.5 block" style={{ color: 'var(--v-text-muted)' }}>{drinkRevenue}</span>
      </MetricTile>

      <MetricTile label="Food" value={String(foodUnits)} accent="cyan" onClick={onBreakdownClick}>
        <span className="text-xs mt-0.5 block" style={{ color: 'var(--v-text-muted)' }}>{foodNet}</span>
        {foodShare !== 100 && (
          <span className="text-[10px] block whitespace-nowrap" style={{ color: 'var(--v-text-dim)' }}>Omar {foodShare}% share</span>
        )}
      </MetricTile>

      <MetricTile label="Unacknowledged" value={String(unacknowledgedCount)} accent={unackAccent} onClick={onAlertsClick}>
        {unacknowledgedCount > 0 && criticalCount > 0 && (
          <span className="mt-1 inline-block">
            <Badge variant="danger">{criticalCount} critical</Badge>
          </span>
        )}
      </MetricTile>

      <MetricTile
        label="Time Elapsed"
        value={formatTimer(elapsed)}
        accent={isLive ? 'green' : undefined}
        className="font-mono tabular-nums"
      />
    </div>
  )
}

// ─── Zone C — Alert Sidebar (wired to real backend via useAlertsForEvent) ─────

const SEVERITY_CFG = {
  critical: {
    color:  'var(--v-pink)',
    bg:     'rgba(255, 61, 113, 0.12)',
  },
  warning: {
    color:  'var(--v-amber)',
    bg:     'rgba(255, 216, 77, 0.12)',
  },
  anomaly: {
    color:  'var(--v-violet)',
    bg:     'rgba(177, 75, 255, 0.12)',
  },
} as const

interface AlertSidebarAlert {
  id: string
  // Nullable (Jul-19 sprint): alert_type='system' / category='unmapped_shop'
  // alerts have no bar by definition.
  bar_id: string | null
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
  // Raw context — used to detect the unmapped-shop 'Map to bar' action
  // (context_json.category === 'unmapped_shop') without a dedicated field.
  context_json: Record<string, unknown>
}
interface AlertSidebarProps {
  open: boolean
  onToggle: () => void
  alerts: AlertSidebarAlert[]
  acknowledged: Set<string>
  onAcknowledge: (id: string) => void
  eventId: string
}

function AlertSidebar({ open, onToggle, alerts, acknowledged, onAcknowledge, eventId }: AlertSidebarProps) {
  const unackedCount = alerts.filter(
    (a) => a.lifecycle_state === 'active' && !acknowledged.has(a.id),
  ).length
  const [mappingAlert, setMappingAlert] = useState<AlertSidebarAlert | null>(null)

  return (
    <div
      className="flex flex-col shrink-0 transition-all duration-200"
      style={{ borderLeft: '0.5px solid var(--v-border)', width: open ? '320px' : '48px' }}
    >

      {/* Header */}
      <div
        className={['flex items-center px-3 py-3 shrink-0', open ? 'justify-between' : 'justify-center'].join(' ')}
        style={{ borderBottom: '0.5px solid var(--v-border)' }}
      >
        {open && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold tracking-wide uppercase" style={{ color: 'var(--v-text-muted)' }}>Alerts</span>
            {unackedCount > 0 && <Badge variant="danger">{unackedCount}</Badge>}
          </div>
        )}
        <button
          onClick={onToggle}
          className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors"
          style={{ color: 'var(--v-text-muted)' }}
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
                <span
                  className="absolute -top-1.5 -right-1.5 w-3.5 h-3.5 rounded-full text-[8px] flex items-center justify-center font-bold"
                  style={{ background: 'var(--v-pink)', color: 'var(--v-bg-base)' }}
                >
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
                className="mx-2 mb-2 rounded-lg p-3 transition-all"
                style={{
                  background: 'var(--v-surface)',
                  border: '0.5px solid var(--v-border)',
                  borderLeft: `3px solid ${cfg.color}`,
                  opacity: acked ? 0.5 : 1,
                }}
              >
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-mono font-bold" style={{ color: 'var(--v-text)' }}>
                      {formatRelativeTime(alert.created_at)}
                    </span>
                    <span className="text-xs font-semibold" style={{ color: cfg.color }}>
                      {alert.bar_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {alert.alert_type === 'anomaly' && (
                      <span
                        className="text-[9px] font-bold px-1 py-0.5 rounded uppercase"
                        style={{ background: SEVERITY_CFG.anomaly.bg, color: SEVERITY_CFG.anomaly.color }}
                      >
                        Anomaly
                      </span>
                    )}
                    <span
                      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase"
                      style={{ background: cfg.bg, color: cfg.color }}
                    >
                      {alert.severity}
                    </span>
                  </div>
                </div>

                <p className="text-xs leading-snug mb-2" style={{ color: acked ? 'var(--v-text-muted)' : 'var(--v-text)' }}>
                  {alert.message}
                </p>

                <div className="flex items-center gap-2">
                  {!acked ? (
                    <button
                      onClick={() => onAcknowledge(alert.id)}
                      className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-colors"
                      style={{ color: 'var(--v-text-muted)', border: '0.5px solid var(--v-border)', background: 'var(--v-surface-raised)' }}
                    >
                      Acknowledge
                    </button>
                  ) : (
                    <span className="text-[10px] italic" style={{ color: 'var(--v-text-dim)' }}>Acknowledged</span>
                  )}

                  {/* Phantom-bar fix (Jul-19 sprint): unmapped Slesh shop_id
                      alerts get an inline resolve action instead of just
                      Acknowledge. */}
                  {alert.alert_type === 'system' &&
                    alert.context_json?.category === 'unmapped_shop' && (
                      <button
                        onClick={() => setMappingAlert(alert)}
                        className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-colors"
                        style={{ color: 'var(--v-bg-base)', background: 'var(--v-cyan)' }}
                      >
                        Map to bar
                      </button>
                    )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {mappingAlert && (
        <MapShopToBarModal
          isOpen
          onClose={() => setMappingAlert(null)}
          eventId={eventId}
          pendingMappingId={String(mappingAlert.context_json?.pending_mapping_id ?? '')}
          sleshShopId={String(mappingAlert.context_json?.slesh_shop_id ?? '')}
        />
      )}
    </div>
  )
}

// ─── Page wrapper: handles loading/error/no-event states ─────────────────────

// Time-elapsed seconds since the event went LIVE. Derived from
// event.started_at (set by go-live transition) — falls back to 0
// if started_at is missing (event not yet promoted or stale data).
function computeElapsedSec(startedAt: string | null | undefined): number {
  if (!startedAt) return 0
  const startMs = new Date(startedAt).getTime()
  if (!Number.isFinite(startMs)) return 0
  return Math.max(0, Math.floor((Date.now() - startMs) / 1000))
}

export default function DashboardPage() {
  const navigate         = useNavigate()
  const { user }         = useAuth()
  const perms            = usePermissions()
  const [searchParams]   = useSearchParams()

  // Role-aware branch: Owner sees the multi-bar overview below; Manager
  // gets their per-bar 'My Bar' view. Two-role model — spec:
  // docs/bar-dashboard-spec.md S3.
  const role = user?.role
  if (role === 'manager') {
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
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--v-text-muted)' }}>
        Finding the active event…
      </div>
    )
  }

  // ── No event live: the season view (real data only — see
  //    SeasonIdleView). The live-event path below is untouched. ──
  if (!eventId) {
    return <SeasonIdleView />
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
  const barAllocationsQ    = useBarAllocations(eventId ?? undefined)
  // Phase 3 Sundance 14: drives the depletion alert engine. Polling this
  // endpoint also triggers fire_depletion_alerts() on the backend so the
  // existing alerts feed keeps surfacing low / critical stock signals
  // automatically. Refresh cadence matches LIVE_REFETCH_MS (15s).
  useBarSupplierStock(eventId)
  const mappingStateQuery  = useBarMappingState(eventId)
  // useMergeBars MUST live with the other top-level data hooks — never
  // below a conditional/early-return path. react-query's useMutation
  // calls useContext internally; if this hook is skipped on one render
  // and called on the next, React tears down the component tree with a
  // hooks-order violation. (Phase 1 bugfix, June 9 2026.)
  const mergeBars          = useMergeBars()
  const barStockQuery      = useBarStockForEvent(eventId)
  const transactionsQuery  = useTransactionsForEvent(eventId)
  const burnRatesQuery     = useBurnRatesForEvent(eventId)
  const kpiQuery           = useEventKpiSummary(eventId)
  const menuQuery          = useMenuPerformance(eventId)
  const productsQuery      = useAllProducts()
  const alertsQuery        = useAlertsForEvent(eventId, { onlyActive: false })
  const alertCountsByBarQuery = useAlertsCountByBar(eventId)

  // For LIVE events:      eventStartMs = started_at, nowMs = Date.now() (ticks)
  // For COMPLETED events: eventStartMs = started_at, nowMs = ended_at  (frozen)
  // For DRAFT/SCHEDULED:  fall back to "now - 1h" so the chart renders empty.
  //
  // liveEvent is only populated for status=LIVE. For past events accessed
  // via ?event_id=, we resolve currentEvent via useEvent(eventId) so charts
  // render the actual event window instead of falling back to "now - 1h".
  const currentEventQuery = useEvent(eventId)
  const currentEvent      = currentEventQuery.data ?? liveEvent ?? undefined

  // ended_at is admin metadata that can be set hours/days after the actual
  // event closes. Sundance 14: last sale was Jun 14 ~22:30, but ended_at
  // was set Jun 15 ~22:30 (we closed the event late in the system),
  // producing a 33h chart with a 24h flat-line tail. Use the timestamp of
  // the last transaction as the de-facto event-end signal instead — it
  // matches the last meaningful data point and avoids that artifact.
  const lastTxMs = useMemo(() => {
    const rows = transactionsQuery.data
    if (!rows?.length) return 0
    let max = 0
    for (const tx of rows) {
      const t = new Date(tx.created_at).getTime()
      if (t > max) max = t
    }
    return max
  }, [transactionsQuery.data])

  const eventStartMs = currentEvent?.started_at
    ? new Date(currentEvent.started_at).getTime()
    : Date.now() - 3600_000

  // For non-live events, prefer last-tx time over ended_at to avoid the
  // long flat tail produced when admin closes the event late.
  const isLive      = currentEvent?.status === 'live'
  const isCompleted = currentEvent?.status === 'completed'
  const endedMs = currentEvent?.ended_at
    ? new Date(currentEvent.ended_at).getTime()
    : Date.now()
  const nowMs = isLive
    ? Date.now()
    : lastTxMs > 0 ? lastTxMs : endedMs

  // Phase E — nowcast forecast; polled every 30s while LIVE. Extended
  // (this chunk) to COMPLETED events for post-mortem "we predicted €X,
  // actual was €Y" review — fetched once (as_of_time=ended_at), no
  // polling, since a completed event's revenue is final. DRAFT stays
  // disabled inside the hook — nothing to predict yet.
  const { forecast, loading: forecastLoading, error: forecastError } =
    useRevenueForecast(eventId, currentEvent?.status, currentEvent?.ended_at)

  // Day 4 — Customer Intelligence panel. Same status-gated polling
  // contract as the revenue forecast above (30s while LIVE, once at
  // ended_at when COMPLETED, disabled otherwise).
  const { data: customerIntel, loading: customerIntelLoading, error: customerIntelError } =
    useCustomerIntelligence(eventId, currentEvent?.status, currentEvent?.ended_at)

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
    context_json:    row.context_json,
  }))
  // reconciliation is used by BarDetailOverlay in v1.1 — prefetched here so
  // it's warm when the overlay opens
  useReconciliation(eventId)

  // ── UI state ──
  const [elapsed,     setElapsed]     = useState(() => computeElapsedSec(liveEvent?.started_at))
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [breakdownOpen, setBreakdownOpen] = useState(false)
  const [revBreakdownOpen, setRevBreakdownOpen] = useState(false)
  const revBreakdownQuery = useEventRevenueBreakdown(eventId, true)  // 2026-07-05: always-on so food bar cards can read fiscal revenue
  const [selectedBar, setSelectedBar] = useState<BarKpi | null>(null)
  // Acknowledged set derived from server data — not local state. The source of
  // truth is alerts[i].acknowledged_at on the server; this Set is just a fast
  // lookup by id for the presentation components.
  const acknowledged = new Set(alerts.filter((a) => a.is_acknowledged).map((a) => a.id))

  // Re-sync the elapsed counter every second against event.started_at
  // rather than just incrementing. This keeps the timer correct on first
  // paint AND resilient to tab-backgrounding where setInterval drift would
  // otherwise accumulate. Re-runs when started_at changes (on go-live).
  useEffect(() => {
    setElapsed(computeElapsedSec(liveEvent?.started_at))
    const id = setInterval(
      () => setElapsed(computeElapsedSec(liveEvent?.started_at)),
      1000,
    )
    return () => clearInterval(id)
  }, [liveEvent?.started_at])

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
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--v-text-muted)' }}>
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
        <p style={{ color: 'var(--v-pink)' }}>Failed to load dashboard data. Check the backend is reachable.</p>
        <Button
          variant="primary"
          onClick={() => {
            barsQuery.refetch()
            barStockQuery.refetch()
            transactionsQuery.refetch()
            productsQuery.refetch()
          }}
        >
          Retry now
        </Button>
        <p className="text-[10px]" style={{ color: 'var(--v-text-dim)' }}>Reconnecting automatically every 15s…</p>
      </div>
    )
  }

  // ── All data arrived — compute the BarKpi view-model ──
  const bars         = barsQuery.data ?? []
  const barStock     = barStockQuery.data ?? []
  const transactions = transactionsQuery.data ?? []
  const products     = productsQuery.data ?? []

  // 2026-07-05: bar_id → fiscal EUR map for food bars from revenue-breakdown.
  // Powers per-bar revenue on FoodBarCard so Twist&Chips shows €154, not €0.
  const foodFiscalByBar: Record<string, number> = {}
  for (const s of revBreakdownQuery.data?.sales.food_by_bar ?? []) {
    foodFiscalByBar[s.bar_id] = parseFloat(s.revenue_eur)
  }
  // 2026-07-19: drinks bars too. Their card revenue was rolled up from
  // stock_transactions, which only exist for drinks that have a recipe —
  // Bar Main read EUR 174 against EUR 500 actually taken. event_orders is
  // the money of record for every bar type.
  for (const s of revBreakdownQuery.data?.sales.drinks_by_bar ?? []) {
    foodFiscalByBar[s.bar_id] = parseFloat(s.revenue_eur)
  }
  const barKpis: BarKpi[] = selectBarKpis({ bars, barStock, transactions, products, burnRates: burnRatesQuery.data ?? [], allocations: barAllocationsQ.data ?? [], eventFoodRevenueSharePct: currentEvent?.food_revenue_share_pct ?? null, foodFiscalRevenueByBarId: foodFiscalByBar })

  // Build per-bar storage lookup — used by BarCard to render the
  // 'N items / X units in warehouse' line. Sums history-preserving
  // allocation rows per bar.
  const storageByBarId = (() => {
    const m = new Map<string, { itemCount: number; totalUnits: number }>()
    const allocs = barAllocationsQ.data ?? []
    for (const bar of allocs) {
      let total = 0
      for (const it of bar.items) total += Number(it.qty_total_allocated)
      m.set(bar.bar_id, { itemCount: bar.items.length, totalUnits: total })
    }
    return m
  })()

  // Partition by mapping state. Live = mapped + stubs (rendered as BarCards
  // in the main grid). Empty = wizard-defined bars with no shop_id yet
  // (rendered as muted EmptyBarCards below the grid). If mapping-state
  // hasn't loaded yet, all bars render as live (pre-Phase-1 behavior).
  const emptyBars          = mappingStateQuery.data?.empty_bars ?? []
  // True if any bar on this event is mapped to a Slesh shop_id (or is
  // an auto-stub from Slesh). Drives the FreshnessBadge gate — the
  // brand-wide Slesh poll freshness is only meaningful when this event
  // is actually wired into Slesh.
  const eventHasSleshBars = (
    (mappingStateQuery.data?.stubs?.length ?? 0) +
    (mappingStateQuery.data?.mapped_bars ?? [])
      .filter((b) => b.slesh_negozio_id != null)
      .length
  ) > 0
  const emptyBarIdSet      = new Set(emptyBars.map((b) => b.id))
  const liveKpis: BarKpi[] = mappingStateQuery.data
    ? barKpis.filter((k) => !emptyBarIdSet.has(k.id))
    : barKpis

  // Stub lookup (sales_count + suggested_target_bar_id) by bar id — used
  // by the inline name-picker dropdown in BarCard to pre-select the
  // device-count-ranked suggestion.
  const stubById = new Map(
    (mappingStateQuery.data?.stubs ?? []).map((s) => [s.id, s] as const),
  )


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
          isLive={isLive}
          onAlertsClick={handleAlertsClick}
          onBreakdownClick={() => setBreakdownOpen(true)}
        />
        <SalesBreakdownModal menu={menuQuery.data ?? null} open={breakdownOpen} onClose={() => setBreakdownOpen(false)} />
        <RevenueBreakdownModal data={revBreakdownQuery.data ?? null} open={revBreakdownOpen} onClose={() => setRevBreakdownOpen(false)} />

        {/* Zone B — Bar card grid */}
        <main className="flex-1 overflow-y-auto p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>Bar Performance</h1>
                <FreshnessBadge eventHasSleshBars={eventHasSleshBars} isLive={isLive} eventId={eventId} />
                <WeatherPill eventId={eventId} />
              </div>
              <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
                {eventName} · {eventStatusLabel} · {barKpis.length} {barKpis.length === 1 ? 'bar' : 'bars'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={() => setRevBreakdownOpen(true)}>Revenue</Button>
              <Button variant="secondary" onClick={() => navigate('/alerts')}>View All Alerts</Button>
            </div>
          </div>

          {barKpis.length === 0 ? (
            <div className="v-card p-12">
              <EmptyState headline="No bars set up" body="Add bars from the event detail page to get started." />
            </div>
          ) : (
            <>
              {barKpis.length > 0 && barKpis.filter((b) => b.revenue_cents === 0 && b.drinks_sold === 0).length / barKpis.length >= 0.8 && (
                <div
                  className="relative overflow-hidden rounded-[var(--v-radius)] px-4 py-3 mb-3 text-[13px] flex items-start gap-2"
                  style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-text-muted)' }}
                >
                  <span className="absolute left-0 top-0 bottom-0 w-[2px]" style={{ background: 'var(--v-cyan)' }} />
                  <svg className="w-4 h-4 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="var(--v-cyan)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />
                  </svg>
                  <span>
                    Most bars are still awaiting their first order. Cards populate as transactions stream in from Slesh POS — bars with activity are shown with live numbers below.
                  </span>
                </div>
              )}

              {/* One 12-column grid, 12px gutter, for the whole "Bar Performance"
                  section below — chart/forecast row, recharge desk, customer
                  intelligence, bar cards, and empty bars all share it so every
                  row lines up and equal-width siblings stretch to equal height
                  (CSS Grid's default align-items: stretch). */}
              <div className="grid grid-cols-12 gap-3">
                {/* Big event-total revenue chart — Actual (live) vs ML Predicted.
                    Locked May 27 2026: replaces the per-bar chart in the
                    overlay. Phase E (Jul 2026): chart (8/12) + forecast KPI
                    sidebar (4/12) when the event is LIVE/COMPLETED. Stacks
                    to full width below the md breakpoint. */}
                <div className="col-span-12 md:col-span-8">
                  <EventRevenueChart
                    transactions={transactionsQuery.data ?? []}
                    eventStartMs={eventStartMs}
                    nowMs={nowMs}
                    predictedCurve={forecast?.predicted_curve}
                    currentRevenueEur={forecast?.current_revenue_eur}
                    hourOffsetFromStart={forecast?.hour_offset_from_start}
                  />
                </div>
                {(isLive || isCompleted) && (
                  <div className="col-span-12 md:col-span-4 flex flex-col gap-1.5">
                    {isCompleted && (
                      <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: 'var(--v-text-dim)' }}>
                        Post-event review
                      </span>
                    )}
                    <div className="flex-1">
                      <RevenueForecastPanel
                        forecast={forecast}
                        loading={forecastLoading}
                        error={forecastError}
                      />
                    </div>
                  </div>
                )}

                {/* Recharge desk — Phase 2 (Jun 21 2026). Money-in row sits
                    between the event-total chart and the bar grid so the
                    page reads top-down: top KPIs → live trend → money came
                    in via top-ups → money got spent across bars. Card hides
                    itself if the event has no recharge stations configured. */}
                <div className="col-span-12">
                  <RechargeDeskCard eventId={eventId} />
                </div>

                {/* Customer Intelligence — Day 4. Same placement rationale
                    as RechargeDeskCard above: sits between the money-in
                    row and the per-bar grid. LIVE/COMPLETED only, same
                    gate as the revenue forecast sidebar. */}
                {(isLive || isCompleted) && (
                  <div className="col-span-12">
                    <CustomerIntelligencePanel
                      eventId={eventId}
                      data={customerIntel}
                      loading={customerIntelLoading}
                      error={customerIntelError}
                    />
                  </div>
                )}

                {liveKpis.map((kpi) => {
                  const stub = stubById.get(kpi.id)
                  const mergeOptions = stub
                    ? {
                        available: emptyBars.filter((b) => b.bar_type === kpi.bar_type),
                        suggested: stub.suggested_target_bar_id,
                        onMerge:   (srcId: string, dstId: string) =>
                          mergeBars.mutate({ src_id: srcId, dst_id: dstId }),
                      }
                    : undefined
                  return (
                    <div key={kpi.id} className="col-span-12 md:col-span-6">
                      <BarCard
                        bar={kpi}
                        criticalAlertCount={alertCountsByBarQuery.data?.get(kpi.id)?.critical ?? 0}
                        onClick={(id) => setSelectedBar(liveKpis.find((b) => b.id === id) ?? null)}
                        transactions={transactionsQuery.data ?? []}
                        products={productsQuery.data ?? []}
                        eventStartMs={eventStartMs}
                        nowMs={nowMs}
                        mergeOptions={mergeOptions}
                        storage={storageByBarId.get(kpi.id)}
                      />
                    </div>
                  )
                })}

                {emptyBars.length > 0 && (
                  <div className="col-span-12 mt-2">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'var(--v-text-muted)' }}>
                      Awaiting activity · {emptyBars.length}
                    </h3>
                  </div>
                )}
                {emptyBars.map((bar) => (
                  <div key={bar.id} className="col-span-6 md:col-span-3">
                    <EmptyBarCard bar={bar} />
                  </div>
                ))}
              </div>
            </>
          )}
        </main>
      </div>

      {/* Zone C — Right column: alerts on top, wristband activity below.
          h-full (not max-h-screen + independent scroll) so the panel's own
          background fills the whole row height — no dark ambient gap
          showing beneath short content. */}
      <div ref={alertsRef} className="flex-none flex flex-col overflow-y-auto h-full" style={{ background: 'var(--v-surface-raised)' }}>
        <AlertSidebar
          open={sidebarOpen}
          onToggle={() => setSidebarOpen((o) => !o)}
          alerts={alerts}
          acknowledged={acknowledged}
          onAcknowledge={handleAcknowledge}
          eventId={eventId}
        />
        {sidebarOpen && (
          <div className="p-3 flex-1" style={{ borderLeft: '0.5px solid var(--v-border)' }}>
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
        eventId={eventId}
        eventStartMs={eventStartMs}
        nowMs={nowMs}
        isLive={isLive}
      />
    </div>
  )
}
