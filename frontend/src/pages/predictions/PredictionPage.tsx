/**
 * PredictionPage — ML demand forecasts.
 * Imports MOCK_PREDICTIONS from mockData; all other data is generated inline.
 */

import { useState } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { MOCK_PREDICTIONS } from '../../lib/mockData'

// ─── Types ────────────────────────────────────────────────────────────────────

type Trend = 'up' | 'stable' | 'down'

// ─── Derived prediction cards from MOCK_PREDICTIONS ──────────────────────────

interface CardData {
  id: number
  product: string
  units: number
  horizon: string
  trend: Trend
  confidence: number // 0-100
}

const CARDS: CardData[] = MOCK_PREDICTIONS.predictions.map((p, i) => ({
  id: i + 1,
  product: p.product,
  units: p.predicted_demand_2h,
  horizon: 'Next 2 hours',
  trend: p.trend as Trend,
  confidence: Math.round(p.confidence * 100),
}))

// ─── Trend config ─────────────────────────────────────────────────────────────

const TREND_CONFIG: Record<Trend, { icon: string; color: string; label: string }> = {
  up:     { icon: '↑', color: '#E53E3E', label: 'Rising'  },
  stable: { icon: '→', color: '#718096', label: 'Stable'  },
  down:   { icon: '↓', color: '#38A169', label: 'Falling' },
}

// ─── Border colour by confidence ─────────────────────────────────────────────

function borderColor(conf: number): string {
  if (conf > 80) return '#38A169'
  if (conf >= 60) return '#ECC94B'
  return '#ED8936'
}

// ─── Forecast Card ───────────────────────────────────────────────────────────

function ForecastCard({ product, units, horizon, trend, confidence }: CardData) {
  const t = TREND_CONFIG[trend]
  const bc = borderColor(confidence)
  const barBg = confidence > 80 ? '#38A169' : confidence >= 60 ? '#ECC94B' : '#ED8936'

  return (
    <div
      style={{ borderLeftColor: bc }}
      className="bg-white border border-[#E2E8F0] border-l-4 rounded-xl shadow-sm p-5 flex flex-col gap-3 hover:shadow-md transition-shadow"
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-[#4A5568] uppercase tracking-widest">{product}</p>
          <p className="text-[11px] text-[#A0AEC0] mt-0.5">{horizon}</p>
        </div>
        <span
          className="text-xl font-bold leading-none"
          style={{ color: t.color }}
          title={t.label}
        >
          {t.icon}
        </span>
      </div>

      {/* Units */}
      <div>
        <span className="text-3xl font-extrabold text-[#1A202C]">{units}</span>
        <span className="text-sm text-[#718096] ml-1">units</span>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex justify-between text-[11px] text-[#718096] mb-1">
          <span>Confidence</span>
          <span className="font-medium" style={{ color: barBg }}>{confidence}%</span>
        </div>
        <div className="h-2 bg-[#EDF2F7] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${confidence}%`, background: barBg }}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Area Chart data — 8 time points, 4-hour window ──────────────────────────

const CHART_DATA = [
  { time: '18:00', Beer: 22, Spirits: 12, Mixers: 30 },
  { time: '18:30', Beer: 28, Spirits: 14, Mixers: 35 },
  { time: '19:00', Beer: 35, Spirits: 18, Mixers: 42 },
  { time: '19:30', Beer: 45, Spirits: 22, Mixers: 52 },
  { time: '20:00', Beer: 58, Spirits: 28, Mixers: 65 },
  { time: '20:30', Beer: 72, Spirits: 34, Mixers: 80 },
  { time: '21:00', Beer: 88, Spirits: 40, Mixers: 96 },
  { time: '21:30', Beer: 105, Spirits: 46, Mixers: 112 },
]

// ─── Accuracy table data ──────────────────────────────────────────────────────

interface AccuracyRow {
  product: string
  predicted: number
  actual: number
}

const ACCURACY_DATA: AccuracyRow[] = [
  { product: 'Beer',     predicted: 140, actual: 156 },
  { product: 'Spirits',  predicted: 95,  actual: 89  },
  { product: 'Mixers',   predicted: 200, actual: 210 },
  { product: 'Wine',     predicted: 40,  actual: 34  },
  { product: 'Premium',  predicted: 60,  actual: 67  },
]

function accuracyPct(predicted: number, actual: number): number {
  return Math.round((1 - Math.abs(predicted - actual) / actual) * 100)
}

type AccuracyStatus = 'Accurate' | 'Close' | 'Off'

function accuracyStatus(predicted: number, actual: number): AccuracyStatus {
  const diff = Math.abs(predicted - actual) / actual * 100
  if (diff <= 10) return 'Accurate'
  if (diff <= 20) return 'Close'
  return 'Off'
}

const STATUS_STYLE: Record<AccuracyStatus, { bg: string; text: string; ring: string }> = {
  Accurate: { bg: '#F0FFF4', text: '#276749', ring: '#9AE6B4' },
  Close:    { bg: '#FFFFF0', text: '#744210', ring: '#F6E05E' },
  Off:      { bg: '#FFF5F5', text: '#9B2C2C', ring: '#FC8181' },
}

// ─── Manual override products ─────────────────────────────────────────────────

const OVERRIDE_PRODUCTS = ['Beer', 'Spirits', 'Mixers', 'Wine', 'Premium']

// ─── Toast ───────────────────────────────────────────────────────────────────

function Toast({ visible }: { visible: boolean }) {
  return (
    <div
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(12px)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        pointerEvents: 'none',
      }}
      className="fixed bottom-6 right-6 z-50 bg-[#1A202C] text-white text-sm font-medium px-5 py-3 rounded-xl shadow-xl flex items-center gap-2"
    >
      <svg className="w-4 h-4 text-[#68D391]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
      </svg>
      Overrides applied successfully
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function PredictionPage() {
  const [overrides, setOverrides] = useState<Record<string, string>>(() =>
    Object.fromEntries(OVERRIDE_PRODUCTS.map((p) => [p, ''])),
  )
  const [toast, setToast] = useState(false)
  const [regenerating, setRegenerating] = useState(false)

  function handleApplyOverrides() {
    setToast(true)
    setTimeout(() => setToast(false), 3000)
  }

  function handleRegenerate() {
    setRegenerating(true)
    setTimeout(() => setRegenerating(false), 1800)
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8">

      {/* ── Page header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-[#1A202C] tracking-tight">
            Demand Predictions
          </h1>
          <p className="text-sm text-[#718096] mt-1">
            ML-based forecasts · Sundance 2026 · Generated&nbsp;
            <span className="font-medium text-[#4A5568]">
              {MOCK_PREDICTIONS.generated_at}
            </span>
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {/* Model badge */}
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#553C9A] bg-[#FAF5FF] border border-[#D6BCFA] px-3 py-1.5 rounded-full">
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10 2a8 8 0 100 16A8 8 0 0010 2zm0 14a6 6 0 110-12 6 6 0 010 12zm-1-5h2v2H9v-2zm0-6h2v4H9V5z" />
            </svg>
            {MOCK_PREDICTIONS.model_type === 'live' ? 'Live Model' : 'Pre-Event Model'}
          </span>

          {/* Regenerate button */}
          <button
            id="btn-regenerate-predictions"
            onClick={handleRegenerate}
            disabled={regenerating}
            className="inline-flex items-center gap-2 text-sm font-semibold text-white bg-[#0694A2] hover:bg-[#047481] disabled:opacity-60 px-4 py-2 rounded-lg shadow-sm transition-all"
          >
            <svg
              className={`w-4 h-4 ${regenerating ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582M20 20v-5h-.581M4.582 9A8 8 0 0120 15M19.418 15A8 8 0 014 9" />
            </svg>
            {regenerating ? 'Regenerating…' : 'Regenerate Predictions'}
          </button>
        </div>
      </div>

      {/* ── Prediction cards (5 in a row) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {CARDS.map((card) => (
          <ForecastCard key={card.id} {...card} />
        ))}
      </div>

      {/* ── Area Chart ── */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl shadow-sm p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-base font-bold text-[#1A202C]">
            Demand Forecast — Next 4 Hours
          </h2>
          <span className="text-xs text-[#718096] bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1 rounded-full font-medium">
            30-min intervals
          </span>
        </div>

        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={CHART_DATA} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <defs>
              <linearGradient id="colorBeer" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#D97706" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#D97706" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="colorSpirits" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#7C3AED" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#7C3AED" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="colorMixers" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#0694A2" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#0694A2" stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#EDF2F7" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 11, fill: '#A0AEC0' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#A0AEC0' }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip
              contentStyle={{
                background: '#1A202C',
                border: 'none',
                borderRadius: '10px',
                color: '#fff',
                fontSize: 12,
                padding: '10px 14px',
              }}
              labelStyle={{ color: '#A0AEC0', marginBottom: 4 }}
              itemStyle={{ color: '#fff' }}
              cursor={{ stroke: '#E2E8F0', strokeWidth: 1 }}
            />
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, paddingTop: 16 }}
            />

            <Area
              type="monotone"
              dataKey="Beer"
              stackId="1"
              stroke="#D97706"
              strokeWidth={2}
              fill="url(#colorBeer)"
              dot={false}
            />
            <Area
              type="monotone"
              dataKey="Spirits"
              stackId="1"
              stroke="#7C3AED"
              strokeWidth={2}
              fill="url(#colorSpirits)"
              dot={false}
            />
            <Area
              type="monotone"
              dataKey="Mixers"
              stackId="1"
              stroke="#0694A2"
              strokeWidth={2}
              fill="url(#colorMixers)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* ── Prediction Accuracy table ── */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-[#E2E8F0]">
          <h2 className="text-base font-bold text-[#1A202C]">Prediction Accuracy</h2>
          <p className="text-xs text-[#A0AEC0] mt-0.5">Compared against last event actuals</p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[#F7FAFC]">
                {['Product', 'Predicted', 'Actual', 'Accuracy %', 'Status'].map((h) => (
                  <th
                    key={h}
                    className="px-6 py-3 text-left text-xs font-semibold text-[#718096] uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#EDF2F7]">
              {ACCURACY_DATA.map((row) => {
                const pct = accuracyPct(row.predicted, row.actual)
                const status = accuracyStatus(row.predicted, row.actual)
                const s = STATUS_STYLE[status]
                return (
                  <tr key={row.product} className="hover:bg-[#F7FAFC] transition-colors">
                    <td className="px-6 py-3.5 font-semibold text-[#1A202C]">{row.product}</td>
                    <td className="px-6 py-3.5 text-[#4A5568]">{row.predicted} units</td>
                    <td className="px-6 py-3.5 text-[#4A5568]">{row.actual} units</td>
                    <td className="px-6 py-3.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-[#1A202C]">{pct}%</span>
                        <div className="flex-1 max-w-[80px] h-1.5 bg-[#EDF2F7] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.min(pct, 100)}%`,
                              background: s.text,
                            }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-3.5">
                      <span
                        className="inline-block text-xs font-semibold px-2.5 py-1 rounded-full border"
                        style={{
                          background: s.bg,
                          color: s.text,
                          borderColor: s.ring,
                        }}
                      >
                        {status}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Manual Override ── */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl shadow-sm p-6">
        <div className="mb-5">
          <h2 className="text-base font-bold text-[#1A202C]">Manual Override</h2>
          <p className="text-xs text-[#A0AEC0] mt-0.5">
            Adjust predicted demand — overrides take effect immediately on save.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
          {OVERRIDE_PRODUCTS.map((product) => (
            <div key={product}>
              <label
                htmlFor={`override-${product}`}
                className="block text-xs font-semibold text-[#4A5568] mb-1.5"
              >
                {product}
              </label>
              <input
                id={`override-${product}`}
                type="number"
                min="0"
                placeholder="e.g. 150"
                value={overrides[product]}
                onChange={(e) =>
                  setOverrides((prev) => ({ ...prev, [product]: e.target.value }))
                }
                className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-[#F7FAFC] text-[#1A202C] placeholder-[#CBD5E0] focus:outline-none focus:ring-2 focus:ring-[#0694A2] focus:border-transparent transition"
              />
            </div>
          ))}
        </div>

        <button
          id="btn-apply-overrides"
          onClick={handleApplyOverrides}
          className="inline-flex items-center gap-2 text-sm font-semibold text-white bg-[#1A202C] hover:bg-[#2D3748] px-5 py-2.5 rounded-lg shadow-sm transition-all"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M5 13l4 4L19 7" />
          </svg>
          Apply Overrides
        </button>
      </div>

      <Toast visible={toast} />
    </div>
  )
}
