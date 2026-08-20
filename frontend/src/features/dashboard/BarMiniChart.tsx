/**
 * BarMiniChart — per-bar stacked bar chart of drink revenue over time.
 *
 * Each time bucket renders as a stacked bar where each segment is one
 * drink product's revenue IN THAT BUCKET (incremental, not cumulative).
 * Tooltip surfaces exact revenue + units sold per drink for that bucket
 * so Omar can see WHICH drinks drove a peak and WHEN.
 *
 * Hesam-requested redesign (replaces the prior 4-category line chart):
 * - Categories don't reflect what was actually sold — Omar wants drink
 *   NAMES on the chart (Gin Tonic, Spritz, Ichnusa) not generic buckets.
 * - All drink products sold at the bar are shown, not a top-N.
 * - Bar chart (not line) keeps the chart readable when 8-15 products
 *   are on screen.
 *
 * Food-only bars render an empty placeholder — drinks-only by design.
 *
 * The math (buildStackedBarPerProduct) lives in chart-buckets.ts; this
 * is a thin presentational wrapper around Recharts BarChart.
 *
 * Colors: each product is colored via colorForCategory(productId) — a
 * deterministic hash into the Vera categorical palette, so a given drink
 * keeps the same color on every bar's chart and every render, regardless
 * of its revenue rank at that particular bar (Day 4/5 restyle).
 */
import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'

import {
  buildStackedBarPerProduct,
  type StackedBarChartPoint,
} from '@/features/dashboard/chart-buckets'
import { buildCategoryByProductId, type ProductLike } from '@/features/dashboard/category-resolver'
import type { StockTransactionRow } from '@/lib/mockData'
import { EmptyState } from '@/design-system/components'
import { colorForCategory } from '@/design-system/categoricalPalette'


// Frontend category buckets that count as drinks. Food and other (deposits
// / unknown) are filtered out so the chart answers "what drinks sold"
// cleanly. Soft drinks live in 'other' today — accepted gap for now.
const DRINK_BUCKETS = new Set(['beer', 'cocktails', 'premium_cocktails', 'wine'])


interface BarMiniChartProps {
  barId:        string
  transactions: StockTransactionRow[]
  products:     ProductLike[]
  eventStartMs: number
  nowMs:        number
  /** Default 140. Pass a smaller number for ultra-compact contexts. */
  height?:      number
  /** Render a compact swatch+name legend below the chart. Default false —
   *  the dashboard's per-card mini charts stay legend-free to save space;
   *  the Bar Detail overlay's hero chart turns this on. */
  showLegend?:  boolean
}


export function BarMiniChart({
  barId,
  transactions,
  products,
  eventStartMs,
  nowMs,
  height = 140,
  showLegend = false,
}: BarMiniChartProps) {
  // (id -> name) for tooltip labels + drink-allow-set for the chart filter.
  // Both derived from the same products array in a single pass.
  const { productNameById, allowedProductIds } = useMemo(() => {
    const nameById: Record<string, string> = {}
    for (const p of products) nameById[p.id] = p.name

    const catByProductId = buildCategoryByProductId(products)
    const drinkIds = new Set<string>()
    for (const [id, cat] of Object.entries(catByProductId)) {
      if (DRINK_BUCKETS.has(String(cat))) drinkIds.add(id)
    }
    return { productNameById: nameById, allowedProductIds: drinkIds }
  }, [products])

  const { points, productOrder } = useMemo(
    () => buildStackedBarPerProduct({
      transactions,
      barId,
      eventStartMs,
      nowMs,
      productNameById,
      allowedProductIds,
    }),
    [transactions, barId, eventStartMs, nowMs, productNameById, allowedProductIds],
  )

  // Empty placeholder so the card height stays consistent across bars.
  if (points.length === 0 || productOrder.length === 0) {
    return (
      <div style={{ height }} className="flex items-center justify-center">
        <EmptyState headline="No drink sales yet" body="Sales will appear here once orders start streaming in." />
      </div>
    )
  }

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={points} margin={{ top: 5, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--v-border)" strokeOpacity={0.5} vertical={false} />
          <XAxis
            dataKey="time_label"
            tick={{ fontSize: 10, fill: 'var(--v-text-dim)' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'var(--v-text-dim)' }}
            tickFormatter={(v: number) => `€${v}`}
            width={45}
          />
          <Tooltip
            content={<StackedBarTooltip />}
            cursor={{ fill: 'rgba(255,255,255,0.04)' }}
          />
          {productOrder.map((id) => (
            <Bar
              key={id}
              dataKey={id}
              stackId="rev"
              fill={colorForCategory(id)}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
      {showLegend && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 px-1">
          {productOrder.map((id) => (
            <span key={id} className="flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--v-text-muted)' }}>
              <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: colorForCategory(id) }} />
              {productNameById[id] ?? id.slice(0, 8)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}


// Custom tooltip — shows exact € and units per drink for the hovered
// time bucket, ranked by revenue desc. Total line at the bottom.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function StackedBarTooltip({ active, payload, label }: any) {
  if (!active || !payload || payload.length === 0) return null

  const point = payload[0].payload as StackedBarChartPoint
  const units = point.__units ?? {}
  const names = point.__names ?? {}

  const rows = payload
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .filter((p: any) => typeof p.value === 'number' && p.value > 0)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .map((p: any) => ({
      name:    (names[p.dataKey] ?? p.dataKey) as string,
      revenue: p.value as number,
      units:   (units[p.dataKey] ?? 0) as number,
      color:   (p.color ?? p.fill) as string,
    }))
    .sort((a: { revenue: number }, b: { revenue: number }) => b.revenue - a.revenue)

  if (rows.length === 0) return null

  const total      = rows.reduce((s: number, r: { revenue: number }) => s + r.revenue, 0)
  const totalUnits = rows.reduce((s: number, r: { units: number }) => s + r.units,   0)

  return (
    <div
      className="rounded-lg px-3 py-2 text-xs min-w-[230px]"
      style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}
    >
      <div className="font-semibold mb-1.5" style={{ color: 'var(--v-text)' }}>{label}</div>
      <div className="space-y-0.5">
        {rows.map((r: { name: string; revenue: number; units: number; color: string }) => (
          <div key={r.name} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-sm shrink-0" style={{ background: r.color }} />
            <span className="flex-1 truncate" style={{ color: 'var(--v-text-muted)' }}>{r.name}</span>
            <span className="tabular-nums font-medium" style={{ color: 'var(--v-text)' }}>
              €{r.revenue.toLocaleString()}
            </span>
            <span className="tabular-nums" style={{ color: 'var(--v-text-dim)' }}>· {r.units}</span>
          </div>
        ))}
      </div>
      <div className="mt-1.5 pt-1.5 flex items-center gap-2 font-semibold" style={{ borderTop: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}>
        <span className="flex-1">Total</span>
        <span className="tabular-nums">€{total.toLocaleString()}</span>
        <span className="tabular-nums font-normal" style={{ color: 'var(--v-text-dim)' }}>· {totalUnits}</span>
      </div>
    </div>
  )
}
