import { useState, useCallback, useMemo } from 'react'
import {
  useLiveEvent,
  useBarsForEvent,
  useBarStockForEvent,
  useAllProducts,
} from '@/features/dashboard/hooks'
import {
  selectInventoryBars,
  selectInventoryProducts,
  type ProductCategory,
  type ProductStatus,
} from '@/features/inventory/selectors'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function stockPct(current: number, initial: number): number {
  if (initial === 0) return 0
  return Math.round((current / initial) * 100)
}

function stockBarColor(pct: number): string {
  if (pct > 60) return 'bg-[#38A169]'
  if (pct > 30) return 'bg-[#D69E2E]'
  return 'bg-[#E53E3E]'
}

function formatDepletion(mins: number): string {
  if (mins <= 0) return 'Depleted'
  if (mins >= 999) return '—'
  if (mins >= 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`
  return `${mins}m`
}

// ─── Style maps ───────────────────────────────────────────────────────────────

const STATUS_CFG: Record<ProductStatus, { label: string; cls: string }> = {
  healthy:  { label: 'Healthy',  cls: 'bg-green-100 text-[#38A169] border border-green-200' },
  warning:  { label: 'Warning',  cls: 'bg-yellow-100 text-[#D69E2E] border border-yellow-200' },
  critical: { label: 'Critical', cls: 'bg-red-100 text-[#E53E3E] border border-red-200' },
  depleted: { label: 'Depleted', cls: 'bg-gray-100 text-[#718096] border border-gray-200' },
}

const CATEGORY_CFG: Record<ProductCategory, string> = {
  Spirits: 'bg-purple-100 text-purple-700 border border-purple-200',
  Beer:    'bg-yellow-100 text-yellow-700 border border-yellow-200',
  Wine:    'bg-pink-100 text-pink-700 border border-pink-200',
  Mixers:  'bg-blue-100 text-blue-700 border border-blue-200',
  Other:   'bg-gray-100 text-[#4A5568] border border-gray-200',
}

const BAR_STATUS_CFG = {
  healthy:  { dot: 'bg-[#38A169]',              label: 'Healthy',   text: 'text-[#38A169]' },
  warning:  { dot: 'bg-[#D69E2E]',              label: 'Low Stock', text: 'text-[#D69E2E]' },
  critical: { dot: 'bg-[#E53E3E] animate-pulse', label: 'Critical',  text: 'text-[#E53E3E]' },
}

const CATEGORIES: ProductCategory[] = ['Spirits', 'Beer', 'Wine', 'Mixers', 'Other']

// ─── Bar lookup map ───────────────────────────────────────────────────────────

// BAR_BY_ID built dynamically from real data inside the component

// ─── Sub-components ───────────────────────────────────────────────────────────

function StockBar({ current, initial }: { current: number; initial: number }) {
  const pct = initial > 0 ? Math.max(0, Math.round((current / initial) * 100)) : 0
  return (
    <div className="flex items-center gap-2 min-w-[100px]">
      <div className="flex-1 h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${stockBarColor(pct)}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="text-xs text-[#4A5568] tabular-nums w-8 text-right">{pct}%</span>
    </div>
  )
}

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ visible }: { visible: boolean }) {
  return (
    <div
      className={[
        'fixed bottom-6 right-6 z-50 bg-[#1A202C] text-white text-sm font-medium',
        'px-4 py-3 rounded-xl shadow-lg transition-all duration-300',
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2 pointer-events-none',
      ].join(' ')}
    >
      Export feature coming soon
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const [selectedBarId, setSelectedBarId]   = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<ProductCategory | 'all'>('all')
  const [toastVisible, setToastVisible]     = useState(false)

  const handleExport = useCallback(() => {
    setToastVisible(true)
    setTimeout(() => setToastVisible(false), 3000)
  }, [])

  // ── Real data via the dashboard hooks ───────────────────────────────────────
  // Same hooks Dashboard uses → single source of truth, consistent polling,
  // shared cache. Inventory only adds a per-product aggregation.
  const liveEvent = useLiveEvent()
  const eventId   = liveEvent.data?.id ?? null
  const eventName = liveEvent.data?.name ?? '—'
  const barsQ     = useBarsForEvent(eventId)
  const stockQ    = useBarStockForEvent(eventId)
  const productsQ = useAllProducts()

  const isLoading = liveEvent.isLoading || barsQ.isLoading || stockQ.isLoading || productsQ.isLoading
  const isError   = liveEvent.isError   || barsQ.isError   || stockQ.isError   || productsQ.isError
  const hasData   = !!barsQ.data && !!stockQ.data && !!productsQ.data

  // ── Selectors: turn raw backend rows into the view model ────────────────────
  const bars = useMemo(
    () => hasData ? selectInventoryBars({
      bars:     barsQ.data!,
      barStock: stockQ.data!,
      products: productsQ.data!,
    }) : [],
    [hasData, barsQ.data, stockQ.data, productsQ.data],
  )
  const products = useMemo(
    () => hasData ? selectInventoryProducts({
      bars:     barsQ.data!,
      barStock: stockQ.data!,
      products: productsQ.data!,
    }) : [],
    [hasData, barsQ.data, stockQ.data, productsQ.data],
  )
  const BAR_BY_ID = useMemo(
    () => Object.fromEntries(bars.map((b) => [b.id, b])),
    [bars],
  )

  // ── Filtered + sorted product list ──────────────────────────────────────────
  const filtered = products
    .filter((p) => selectedBarId === null || p.bar_id === selectedBarId)
    .filter((p) => selectedCategory === 'all' || p.category === selectedCategory)
    .slice()
    .sort((a, z) => a.estimated_depletion_minutes - z.estimated_depletion_minutes)

  // ── Footer stats ────────────────────────────────────────────────────────────
  const atRiskCount = filtered.filter(
    (p) => p.status === 'warning' || p.status === 'critical' || p.status === 'depleted',
  ).length

  // ── Three-state UX: loading / error / empty ─────────────────────────────────
  if (isLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-[#1A202C]">Inventory Overview</h1>
        <div className="mt-8 text-center text-sm text-[#718096]">Loading inventory…</div>
      </div>
    )
  }
  if (isError) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-[#1A202C]">Inventory Overview</h1>
        <div className="mt-8 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          Couldn't load inventory data. Refresh the page or try again later.
        </div>
      </div>
    )
  }
  if (!eventId) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-[#1A202C]">Inventory Overview</h1>
        <div className="mt-8 bg-[#F7FAFC] border border-[#E2E8F0] rounded-xl p-8 text-center text-sm text-[#4A5568]">
          No live event right now. Inventory tracks the active event in real time.
        </div>
      </div>
    )
  }
  if (bars.length === 0) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold text-[#1A202C]">Inventory Overview</h1>
        <p className="text-sm text-[#4A5568] mt-1">{eventName}</p>
        <div className="mt-8 bg-[#F7FAFC] border border-[#E2E8F0] rounded-xl p-8 text-center text-sm text-[#4A5568]">
          No bars configured for this event yet. Add bars from the event detail page.
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-[#1A202C]">Inventory Overview</h1>
        <p className="text-sm text-[#4A5568] mt-1">{eventName} · Live · {products.length} products across {bars.length} bars</p>
      </div>

      {/* ── Filters ───────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 flex-wrap mb-5">

        {/* Bar filter pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setSelectedBarId(null)}
            className={[
              'text-xs font-semibold px-3.5 py-1.5 rounded-full border transition-colors',
              selectedBarId === null
                ? 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:bg-[#F7FAFC]',
            ].join(' ')}
          >
            All Bars
          </button>
          {bars.map((bar) => (
            <button
              key={bar.id}
              onClick={() => setSelectedBarId(bar.id)}
              className={[
                'text-xs font-semibold px-3.5 py-1.5 rounded-full border transition-colors',
                selectedBarId === bar.id
                  ? 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                  : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:bg-[#F7FAFC]',
              ].join(' ')}
            >
              {bar.name}
            </button>
          ))}
        </div>

        {/* Category dropdown */}
        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value as ProductCategory | 'all')}
          className="text-sm border border-[#E2E8F0] rounded-lg px-3 py-1.5 bg-white text-[#4A5568] focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/20 focus:border-[#1E5A8D] transition"
        >
          <option value="all">All Categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* ── Bar Summary Cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {bars.map((bar) => {
          const pct = stockPct(bar.current_stock, bar.initial_stock)
          const cfg = BAR_STATUS_CFG[bar.status]
          const isSelected = selectedBarId === bar.id
          return (
            <button
              key={bar.id}
              onClick={() => setSelectedBarId(isSelected ? null : bar.id)}
              className={[
                'bg-white rounded-xl border p-4 text-left transition-all shadow-sm hover:shadow-md',
                isSelected
                  ? 'border-[#1E5A8D] ring-2 ring-[#1E5A8D]/20'
                  : 'border-[#E2E8F0]',
              ].join(' ')}
            >
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
                <span className="text-xs font-bold text-[#1A202C] truncate">{bar.name}</span>
              </div>
              <p className="text-sm font-bold text-[#1A202C] mb-1.5">
                {bar.current_stock}
                <span className="text-xs font-normal text-[#4A5568]">/{bar.initial_stock} bottles</span>
              </p>
              <div className="h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden mb-1.5">
                <div
                  className={`h-full rounded-full ${stockBarColor(pct)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className={`text-[10px] font-semibold ${cfg.text}`}>{cfg.label}</p>
            </button>
          )
        })}
      </div>

      {/* ── Product Table ─────────────────────────────────────────────────── */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[#F7FAFC] border-b border-[#E2E8F0]">
                {[
                  { label: 'Product Name',     align: 'text-left'  },
                  { label: 'Bar',              align: 'text-left'  },
                  { label: 'Category',         align: 'text-left'  },
                  { label: 'Current',          align: 'text-right' },
                  { label: 'Initial',          align: 'text-right' },
                  { label: 'Stock Level',      align: 'text-left'  },
                  { label: 'Status',           align: 'text-left'  },
                  { label: 'Burn Rate',        align: 'text-right' },
                  { label: 'Time to Depletion',align: 'text-right' },
                  { label: 'Unit Price',       align: 'text-right' },
                ].map(({ label, align }) => (
                  <th
                    key={label}
                    className={`px-4 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide whitespace-nowrap ${align}`}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-5 py-10 text-center text-sm text-[#4A5568]">
                    No products match the selected filters.
                  </td>
                </tr>
              ) : (
                filtered.map((p) => {
                  const statusCfg   = STATUS_CFG[p.status]
                  const bar         = BAR_BY_ID[p.bar_id]
                  const urgent      = p.estimated_depletion_minutes > 0 && p.estimated_depletion_minutes < 45
                  const rowDanger   = p.status === 'critical' || p.status === 'depleted'

                  return (
                    <tr
                      key={p.id}
                      className={[
                        'border-b border-[#E2E8F0] last:border-0 transition-colors',
                        rowDanger ? 'bg-red-50/40 hover:bg-red-50/60' : 'hover:bg-[#F7FAFC]',
                      ].join(' ')}
                    >
                      {/* Product Name */}
                      <td className="px-4 py-3 font-semibold text-[#1A202C] whitespace-nowrap">
                        {p.product_name}
                      </td>

                      {/* Bar */}
                      <td className="px-4 py-3 text-[#4A5568] whitespace-nowrap">
                        {bar?.name ?? '—'}
                      </td>

                      {/* Category */}
                      <td className="px-4 py-3">
                        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${CATEGORY_CFG[p.category]}`}>
                          {p.category}
                        </span>
                      </td>

                      {/* Current Stock */}
                      <td className="px-4 py-3 text-right font-mono font-semibold text-[#1A202C]">
                        {p.current_stock}
                      </td>

                      {/* Initial Stock */}
                      <td className="px-4 py-3 text-right font-mono text-[#4A5568]">
                        {p.initial_stock}
                      </td>

                      {/* Stock Bar */}
                      <td className="px-4 py-3">
                        <StockBar current={p.current_stock} initial={p.initial_stock} />
                      </td>

                      {/* Status Badge */}
                      <td className="px-4 py-3">
                        <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${statusCfg.cls}`}>
                          {statusCfg.label}
                        </span>
                      </td>

                      {/* Burn Rate */}
                      <td className="px-4 py-3 text-right text-[#4A5568] tabular-nums whitespace-nowrap">
                        {p.consumption_rate > 0 ? `${p.consumption_rate} btl/hr` : '—'}
                      </td>

                      {/* Time to Depletion */}
                      <td className={[
                        'px-4 py-3 text-right tabular-nums whitespace-nowrap',
                        urgent ? 'font-bold text-[#E53E3E]' : 'text-[#1A202C]',
                        p.status === 'depleted' ? 'text-[#718096]' : '',
                      ].join(' ')}>
                        {formatDepletion(p.estimated_depletion_minutes)}
                      </td>

                      {/* Unit Price */}
                      <td className="px-4 py-3 text-right text-[#4A5568] tabular-nums">
                        €{p.unit_price.toFixed(2)}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* ── Table Footer ──────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-3 bg-[#F7FAFC] border-t border-[#E2E8F0] flex-wrap gap-3">
          <div className="flex items-center gap-5">
            <span className="text-xs text-[#4A5568]">
              <span className="font-semibold text-[#1A202C]">{filtered.length}</span> products
            </span>
            <span className={`text-xs ${atRiskCount > 0 ? 'text-[#E53E3E] font-semibold' : 'text-[#4A5568]'}`}>
              {atRiskCount > 0 ? (
                <>
                  <span className="font-bold">{atRiskCount}</span> at risk
                </>
              ) : (
                'No products at risk'
              )}
            </span>
          </div>

          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 text-xs font-semibold text-[#4A5568] border border-[#E2E8F0] bg-white hover:bg-[#F7FAFC] px-3 py-1.5 rounded-lg transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Export CSV
          </button>
        </div>
      </div>

      <Toast visible={toastVisible} />
    </div>
  )
}
