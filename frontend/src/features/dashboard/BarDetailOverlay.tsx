/**
 * BarDetailOverlay — slides in from the right when a BarCard is clicked.
 * Sections: Revenue chart, Drinks breakdown, Stock table,
 *           Consumption ratios, Alerts, Chat.
 */
import { useState, useEffect, useRef } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { MOCK_PRODUCTS, MOCK_ALERTS, MOCK_CHAT_MESSAGES } from '@/lib/mockData'
import type { Bar, Product } from '@/lib/mockData'

// ─── Data helpers ─────────────────────────────────────────────────────────────

/** Hours elapsed since event start — used for consumption calculations. */
const TIME_ELAPSED_H = 2.58  // ~2h 35m

function generateRevenueData(bar: Bar): { time: string; actual: number; predicted: number }[] {
  // Cumulative growth curves (12 × 15-min slots, 19:00 → 21:45)
  const growth  = [0.02, 0.05, 0.10, 0.18, 0.29, 0.40, 0.53, 0.65, 0.75, 0.84, 0.92, 1.00]
  const predict = [0.03, 0.07, 0.12, 0.20, 0.30, 0.41, 0.52, 0.63, 0.73, 0.82, 0.91, 1.00]
  // Per-bar deterministic noise so each chart looks different
  const jitter: Record<number, number[]> = {
    1: [1.01, 0.99, 1.02, 0.98, 1.04, 0.97, 1.03, 0.99, 1.02, 0.98, 1.01, 1.00],
    2: [0.99, 1.02, 0.97, 1.03, 0.97, 1.04, 0.98, 1.02, 0.97, 1.03, 0.99, 1.00],
    3: [1.02, 0.97, 1.03, 0.98, 1.02, 0.97, 1.03, 0.98, 1.01, 0.98, 1.01, 1.00],
    4: [0.97, 1.03, 0.96, 1.04, 0.95, 1.05, 0.96, 1.03, 0.97, 1.04, 0.98, 1.00],
  }
  const noise = jitter[bar.id] ?? growth.map(() => 1)

  return Array.from({ length: 12 }, (_, i) => {
    const mins = 19 * 60 + i * 15
    const h    = Math.floor(mins / 60)
    const m    = mins % 60
    return {
      time:      `${h}:${String(m).padStart(2, '0')}`,
      actual:    Math.round(bar.revenue * growth[i] * noise[i]),
      predicted: Math.round(bar.revenue * predict[i]),
    }
  })
}

// ─── Style maps ───────────────────────────────────────────────────────────────

const STATUS_DOT: Record<Bar['status'], string> = {
  healthy:  'bg-[#38A169]',
  warning:  'bg-[#D69E2E]',
  critical: 'bg-[#E53E3E] animate-pulse',
}

const STATUS_LABEL: Record<Bar['status'], { text: string; cls: string }> = {
  healthy:  { text: 'Healthy',   cls: 'bg-green-100 text-[#38A169]' },
  warning:  { text: 'Low Stock', cls: 'bg-yellow-100 text-[#D69E2E]' },
  critical: { text: 'Critical',  cls: 'bg-red-100 text-[#E53E3E]' },
}

const PRODUCT_STATUS_CFG: Record<Product['status'], { label: string; cls: string }> = {
  healthy:  { label: 'Healthy',  cls: 'bg-green-100 text-[#38A169] border border-green-200' },
  warning:  { label: 'Warning',  cls: 'bg-yellow-100 text-[#D69E2E] border border-yellow-200' },
  critical: { label: 'Critical', cls: 'bg-red-100 text-[#E53E3E] border border-red-200' },
  depleted: { label: 'Depleted', cls: 'bg-gray-100 text-[#718096] border border-gray-200' },
}

const SEVERITY_CFG = {
  critical: {
    badge:   'bg-red-100 text-[#E53E3E] border border-red-200',
    borderL: 'border-l-[#E53E3E]',
  },
  warning: {
    badge:   'bg-yellow-100 text-[#D69E2E] border border-yellow-200',
    borderL: 'border-l-[#D69E2E]',
  },
  anomaly: {
    badge:   'bg-orange-100 text-[#E67E22] border border-orange-200',
    borderL: 'border-l-[#E67E22]',
  },
} as const

const TIER_CFG = {
  B: { label: 'Basic',    bg: 'bg-blue-50',   text: 'text-blue-700',   border: 'border-blue-200',   ring: 'ring-2 ring-blue-400' },
  S: { label: 'Standard', bg: 'bg-indigo-50', text: 'text-indigo-700', border: 'border-indigo-200', ring: 'ring-2 ring-indigo-400' },
  P: { label: 'Premium',  bg: 'bg-violet-50', text: 'text-violet-700', border: 'border-violet-200', ring: 'ring-2 ring-violet-400' },
  U: { label: 'Upgrade',  bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  ring: 'ring-2 ring-amber-400' },
} as const

// ─── Small helpers ────────────────────────────────────────────────────────────

function formatDepletion(mins: number): string {
  if (mins <= 0) return 'Depleted'
  if (mins >= 999) return '—'
  if (mins >= 60)  return `${Math.floor(mins / 60)}h ${mins % 60}m`
  return `${mins}m`
}

function SectionHeader({ title }: { title: string }) {
  return (
    <h2 className="text-[10px] font-bold text-[#4A5568] uppercase tracking-widest mb-3 pb-2 border-b border-[#E2E8F0]">
      {title}
    </h2>
  )
}

// ─── Revenue chart tooltip ────────────────────────────────────────────────────

interface TooltipProps {
  active?:  boolean
  payload?: { dataKey: string; value: number; color: string }[]
  label?:   string
}
function RevenueTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg shadow-md px-3 py-2 text-xs">
      <p className="font-semibold text-[#1A202C] mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.dataKey === 'actual' ? 'Actual' : 'Predicted'}: €{p.value.toLocaleString()}
        </p>
      ))}
    </div>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
  bar:     Bar | null
  onClose: () => void
}

export function BarDetailOverlay({ bar, onClose }: Props) {
  const isOpen = bar !== null

  // Retain data during the close animation (bar becomes null before panel slides out)
  const prevBarRef = useRef<Bar | null>(null)
  if (bar !== null) prevBarRef.current = bar
  const b = bar ?? prevBarRef.current

  const [selectedTier, setSelectedTier] = useState<keyof typeof TIER_CFG | null>(null)
  const [chatInput, setChatInput]       = useState('')

  // Reset UI state when a different bar is opened
  useEffect(() => {
    setSelectedTier(null)
    setChatInput('')
  }, [bar?.id])

  // Escape key closes
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  // ── Derived data ────────────────────────────────────────────────────────────
  const products = b ? MOCK_PRODUCTS.filter((p) => p.bar_id === b.id) : []
  const sortedProducts = [...products].sort(
    (a, z) => a.estimated_depletion_minutes - z.estimated_depletion_minutes,
  )
  const barAlerts   = b ? MOCK_ALERTS.filter((a) => a.bar_id === b.id) : []
  const barMessages = b
    ? MOCK_CHAT_MESSAGES.filter((m) => m.bar_id === b.id).slice(-3)
    : []
  const revenueData = b ? generateRevenueData(b) : []

  return (
    <>
      {/* ── Backdrop ─────────────────────────────────────────────────────── */}
      <div
        className={[
          'fixed inset-0 bg-black/50 z-40 transition-opacity duration-300',
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none',
        ].join(' ')}
        onClick={onClose}
      />

      {/* ── Slide-in panel ───────────────────────────────────────────────── */}
      <div
        className={[
          'fixed right-0 top-0 h-full w-[70%] bg-[#F7FAFC] z-50 shadow-2xl flex flex-col',
          'transition-transform duration-300 ease-in-out',
          isOpen ? 'translate-x-0' : 'translate-x-full',
        ].join(' ')}
      >
        {b && (
          <>
            {/* ── 1. Header ─────────────────────────────────────────────── */}
            <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-[#E2E8F0] shrink-0 shadow-sm">
              <div className="flex items-center gap-2.5">
                <div className={`w-3 h-3 rounded-full shrink-0 ${STATUS_DOT[b.status]}`} />
                <h1 className="text-lg font-bold text-[#1A202C]">{b.name}</h1>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_LABEL[b.status].cls}`}>
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

            {/* ── Scrollable body ───────────────────────────────────────── */}
            <div className="flex-1 overflow-y-auto">
              <div className="p-6 space-y-5">

                {/* ── 2. Revenue ──────────────────────────────────────── */}
                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Revenue" />
                  <div className="flex items-end gap-3 mb-4">
                    <p className="text-3xl font-bold text-[#1A202C]">
                      €{b.revenue.toLocaleString()}
                    </p>
                    <span className="text-xs font-semibold bg-green-100 text-[#38A169] border border-green-200 px-2 py-1 rounded-full mb-1">
                      +12% vs prediction
                    </span>
                  </div>

                  <div className="h-44">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={revenueData}
                        margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                        <XAxis
                          dataKey="time"
                          tick={{ fontSize: 10, fill: '#4A5568' }}
                          interval={2}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          tick={{ fontSize: 10, fill: '#4A5568' }}
                          tickLine={false}
                          axisLine={false}
                          width={46}
                          tickFormatter={(v: number) => `€${(v / 1000).toFixed(1)}k`}
                        />
                        <Tooltip content={<RevenueTooltip />} />
                        {/* ML predicted — dashed purple */}
                        <Line
                          type="monotone"
                          dataKey="predicted"
                          stroke="#6C63FF"
                          strokeWidth={1.5}
                          strokeDasharray="5 5"
                          dot={false}
                        />
                        {/* Actual — solid navy */}
                        <Line
                          type="monotone"
                          dataKey="actual"
                          stroke="#1E5A8D"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Legend */}
                  <div className="flex items-center gap-5 mt-2">
                    <span className="flex items-center gap-1.5 text-xs text-[#4A5568]">
                      <span className="inline-block w-6 h-0.5 bg-[#1E5A8D] rounded" />
                      Actual
                    </span>
                    <span className="flex items-center gap-1.5 text-xs text-[#4A5568]">
                      <svg width="24" height="4">
                        <line x1="0" y1="2" x2="24" y2="2" stroke="#6C63FF" strokeWidth="1.5" strokeDasharray="4 3" />
                      </svg>
                      ML Predicted
                    </span>
                  </div>
                </section>

                {/* ── 3. Drinks Breakdown ─────────────────────────────── */}
                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Drinks Breakdown" />
                  <div className="flex gap-3">
                    {(['B', 'S', 'P', 'U'] as const).map((tier) => {
                      const count  = b.drinks_breakdown[tier]
                      const pct    = Math.round((count / Math.max(b.drinks_sold, 1)) * 100)
                      const cfg    = TIER_CFG[tier]
                      const active = selectedTier === tier
                      return (
                        <button
                          key={tier}
                          onClick={() => setSelectedTier(active ? null : tier)}
                          className={[
                            'flex flex-col items-center px-4 py-3 rounded-xl border transition-all flex-1',
                            cfg.bg, cfg.text, cfg.border,
                            active ? cfg.ring : '',
                          ].join(' ')}
                        >
                          <span className="text-2xl font-bold leading-none">{count}</span>
                          <span className="text-[11px] font-semibold mt-1">{cfg.label}</span>
                          <span className="text-[10px] opacity-60 mt-0.5">{pct}%</span>
                        </button>
                      )
                    })}
                  </div>
                </section>

                {/* ── 4. Stock Table ──────────────────────────────────── */}
                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title={`Stock — ${sortedProducts.length} products`} />
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
                        {sortedProducts.map((p) => {
                          // Derive status from depletion time per MVP spec:
                          //   Depleted (stock == 0) > Critical (<45m) > Warning (45-120m) > Healthy (>120m)
                          const m = p.estimated_depletion_minutes
                          const derivedStatus =
                            p.current_stock === 0 ? 'depleted' :
                            m < 45              ? 'critical' :
                            m < 120             ? 'warning'  :
                                                  'healthy'
                          const st     = PRODUCT_STATUS_CFG[derivedStatus]
                          const urgent = m < 45
                          return (
                            <tr
                              key={p.id}
                              className={[
                                'border-b border-[#F7FAFC]',
                                urgent ? 'bg-red-50/50' : 'hover:bg-[#F7FAFC]',
                              ].join(' ')}
                            >
                              <td className="py-2.5 pr-3 font-medium text-[#1A202C] whitespace-nowrap">
                                {p.product_name}
                              </td>
                              <td className="py-2.5 pr-3 text-[#4A5568]">{p.category}</td>
                              <td
                                className="py-2.5 pr-3 font-mono text-[#1A202C]"
                                title={`Started with ${p.initial_stock} bottles`}
                              >
                                {p.current_stock} left
                                <span className="text-[#4A5568] ml-1">
                                  ({Math.round((p.current_stock / p.initial_stock) * 100)}%)
                                </span>
                              </td>
                              <td className="py-2.5 pr-3">
                                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${st.cls}`}>
                                  {st.label}
                                </span>
                              </td>
                              <td className="py-2.5 pr-3 text-[#4A5568]">
                                {p.consumption_rate} btl/hr
                              </td>
                              <td className={`py-2.5 font-semibold ${urgent ? 'text-[#E53E3E]' : 'text-[#1A202C]'}`}>
                                {formatDepletion(p.estimated_depletion_minutes)}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </section>

                {/* ── 6. Alerts ───────────────────────────────────────── */}
                {barAlerts.length > 0 && (
                  <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                    <SectionHeader title={`Alerts — ${barAlerts.length}`} />
                    <div className="space-y-2">
                      {barAlerts.map((alert) => {
                        const cfg = SEVERITY_CFG[alert.severity]
                        return (
                          <div
                            key={alert.id}
                            className={[
                              'border-l-4 rounded-lg p-3 border border-[#E2E8F0]',
                              cfg.borderL,
                              alert.is_acknowledged ? 'bg-[#F7FAFC] opacity-55' : 'bg-white',
                            ].join(' ')}
                          >
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[10px] font-mono font-bold text-[#1A202C]">
                                {alert.created_at}
                              </span>
                              <div className="flex items-center gap-1.5">
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
                            <p className={`text-xs leading-snug ${alert.is_acknowledged ? 'text-[#4A5568]' : 'text-[#1A202C]'}`}>
                              {alert.message}
                            </p>
                            {alert.is_acknowledged && (
                              <p className="text-[10px] text-[#4A5568] italic mt-1">Acknowledged</p>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </section>
                )}

                {/* ── 7. Chat ─────────────────────────────────────────── */}
                <section className="bg-white rounded-xl border border-[#E2E8F0] p-5 shadow-sm">
                  <SectionHeader title="Chat" />

                  {/* Last 3 messages */}
                  {barMessages.length > 0 ? (
                    <div className="space-y-2 mb-4">
                      {barMessages.map((msg) => (
                        <div
                          key={msg.id}
                          className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-3 py-2.5"
                        >
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-xs font-semibold text-[#1A202C]">
                              {msg.sender_name}
                            </span>
                            <span className="text-[10px] font-mono text-[#4A5568]">
                              {msg.timestamp}
                            </span>
                          </div>
                          <p className="text-xs text-[#4A5568] leading-snug">{msg.message}</p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[#4A5568] italic mb-4">
                      No messages for this bar yet.
                    </p>
                  )}

                  {/* Input */}
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && chatInput.trim()) setChatInput('')
                      }}
                      placeholder={`Send message to ${b.name} manager…`}
                      className="flex-1 text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 bg-white text-[#1A202C] placeholder:text-[#CBD5E0] focus:outline-none focus:ring-2 focus:ring-[#1ABC9C]/30 focus:border-[#1ABC9C] transition"
                    />
                    <button
                      onClick={() => { if (chatInput.trim()) setChatInput('') }}
                      className="px-4 py-2 text-sm font-semibold text-white rounded-lg transition-colors"
                      style={{ backgroundColor: '#1ABC9C' }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#17a589')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#1ABC9C')}
                    >
                      Send
                    </button>
                  </div>
                </section>

              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
