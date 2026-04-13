/**
 * DashboardPage — Owner-only operational command center.
 * Zone A: KPI strip  |  Zone B: 2×2 bar cards  |  Zone C: Alert sidebar
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePermissions } from '@/features/auth/usePermissions'
import { BarCard } from '@/features/dashboard/BarCard'
import { BarDetailOverlay } from '@/features/dashboard/BarDetailOverlay'
import { MOCK_BARS, MOCK_ALERTS, MOCK_EVENT } from '@/lib/mockData'
import type { Alert, Bar } from '@/lib/mockData'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTimer(totalSecs: number) {
  const h = Math.floor(totalSecs / 3600)
  const m = Math.floor((totalSecs % 3600) / 60)
  const s = totalSecs % 60
  return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`
}

// ─── Zone A — KPI Strip ───────────────────────────────────────────────────────

interface KpiStripProps {
  elapsed: number
  unacknowledgedCount: number
  onAlertsClick: () => void
}

function KpiStrip({ elapsed, unacknowledgedCount, onAlertsClick }: KpiStripProps) {
  const totalRevenue = MOCK_BARS.reduce((sum, b) => sum + b.revenue, 0)
  const totalDrinks  = MOCK_BARS.reduce((sum, b) => sum + b.drinks_sold, 0)
  const tierTotals   = MOCK_BARS.reduce(
    (acc, b) => ({
      B: acc.B + b.drinks_breakdown.B,
      S: acc.S + b.drinks_breakdown.S,
      P: acc.P + b.drinks_breakdown.P,
      U: acc.U + b.drinks_breakdown.U,
    }),
    { B: 0, S: 0, P: 0, U: 0 },
  )

  return (
    <div className="bg-white border-b border-[#E2E8F0] px-5 py-3 flex items-center gap-0 overflow-x-auto shrink-0 shadow-sm">

      {/* Total Revenue */}
      <div className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0">
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Total Revenue
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none">
            €{totalRevenue.toLocaleString()}
          </p>
        </div>
        <span className="text-xs font-semibold bg-green-100 text-[#38A169] border border-green-200 px-2 py-1 rounded-full whitespace-nowrap">
          +12% vs prediction
        </span>
      </div>

      {/* Drinks Sold */}
      <div className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0">
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5">
            Drinks Sold
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none">{totalDrinks}</p>
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex gap-1.5">
            {(['B', 'S', 'P', 'U'] as const).map((t) => {
              const TIER_LABELS = { B: 'Basic', S: 'Standard', P: 'Premium', U: 'Ultra' } as const
              return (
                <span
                  key={t}
                  className="text-[10px] font-bold bg-[#F7FAFC] border border-[#E2E8F0] text-[#4A5568] px-2 py-0.5 rounded whitespace-nowrap"
                >
                  {TIER_LABELS[t]} {tierTotals[t]}
                </span>
              )
            })}
          </div>
        </div>
      </div>

      {/* Active Alerts */}
      <button
        onClick={onAlertsClick}
        className="flex items-center gap-3 pr-5 border-r border-[#E2E8F0] mr-5 shrink-0 hover:bg-red-50 rounded-lg px-3 py-1 -mx-3 transition-colors"
      >
        <div>
          <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-widest mb-0.5 text-left">
            Active Alerts
          </p>
          <p className="text-2xl font-bold text-[#1A202C] leading-none text-left">
            {unacknowledgedCount}
          </p>
        </div>
        {unacknowledgedCount > 0 && (
          <span className="flex items-center gap-1 text-xs font-bold bg-red-100 text-[#E53E3E] border border-red-200 px-2 py-1 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E53E3E] animate-pulse" />
            {MOCK_ALERTS.filter((a) => a.severity === 'critical').length} critical
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

// ─── Zone C — Alert Sidebar ───────────────────────────────────────────────────

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

interface AlertSidebarProps {
  open: boolean
  onToggle: () => void
  acknowledged: Set<number>
  onAcknowledge: (id: number) => void
}

function AlertSidebar({ open, onToggle, acknowledged, onAcknowledge }: AlertSidebarProps) {
  const unackedCount = MOCK_ALERTS.filter((a) => !acknowledged.has(a.id)).length

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

      {/* Alert list */}
      {open && (
        <div className="flex-1 overflow-y-auto py-2">
          {MOCK_ALERTS.map((alert) => {
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
                      {alert.created_at}
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

// ─── Page ─────────────────────────────────────────────────────────────────────

const START_ELAPSED = 2 * 3600 + 35 * 60  // 2h 35m

export default function DashboardPage() {
  const navigate    = useNavigate()
  const perms       = usePermissions()
  const alertsRef   = useRef<HTMLDivElement>(null)

  const [elapsed, setElapsed]           = useState(START_ELAPSED)
  const [sidebarOpen, setSidebarOpen]   = useState(true)
  const [selectedBar, setSelectedBar]   = useState<Bar | null>(null)
  const [acknowledged, setAcknowledged] = useState<Set<number>>(
    () => new Set(MOCK_ALERTS.filter((a) => a.is_acknowledged).map((a) => a.id)),
  )

  // Redirect non-owners (belt-and-suspenders — route guard already covers this)
  if (!perms.canViewAllBars) {
    navigate('/', { replace: true })
    return null
  }

  useEffect(() => {
    const id = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const handleAcknowledge = useCallback((id: number) => {
    setAcknowledged((prev) => new Set(prev).add(id))
  }, [])

  function handleAlertsClick() {
    setSidebarOpen(true)
    alertsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const unacknowledgedCount = MOCK_ALERTS.filter((a) => !acknowledged.has(a.id)).length

  return (
    <div className="flex h-full overflow-hidden">

      {/* Left column — Zone A + Zone B (75%) */}
      <div className="flex flex-col flex-1 overflow-hidden">

        {/* Zone A — KPI Strip */}
        <KpiStrip
          elapsed={elapsed}
          unacknowledgedCount={unacknowledgedCount}
          onAlertsClick={handleAlertsClick}
        />

        {/* Zone B — Bar card grid */}
        <main className="flex-1 overflow-y-auto p-5 bg-[#F7FAFC]">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-lg font-bold text-[#1A202C]">Bar Performance</h1>
              <p className="text-xs text-[#4A5568] mt-0.5">
                {MOCK_EVENT.name} · Live · {MOCK_BARS.length} bars active
              </p>
            </div>
            <button
              onClick={() => navigate('/alerts')}
              className="text-xs font-medium text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#F0F7FF] transition-colors"
            >
              View All Alerts
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {MOCK_BARS.map((bar) => (
              <BarCard
                key={bar.id}
                bar={bar}
                onClick={(id) => setSelectedBar(MOCK_BARS.find((b) => b.id === id) ?? null)}
              />
            ))}
          </div>
        </main>
      </div>

      {/* Zone C — Alert sidebar (25%) */}
      <div ref={alertsRef} className="flex-none">
        <AlertSidebar
          open={sidebarOpen}
          onToggle={() => setSidebarOpen((o) => !o)}
          acknowledged={acknowledged}
          onAcknowledge={handleAcknowledge}
        />
      </div>

      {/* Bar detail overlay — sits above everything */}
      <BarDetailOverlay
        bar={selectedBar}
        onClose={() => setSelectedBar(null)}
      />
    </div>
  )
}
