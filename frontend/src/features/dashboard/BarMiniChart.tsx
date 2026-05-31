/**
 * BarMiniChart — small 5-line per-bar revenue chart for inside bar cards.
 *
 * Renders ONE chart per bar showing cumulative revenue over time, with
 * one line per drink category (beer / cocktails / premium_cocktails /
 * wine) plus a thicker navy TOTAL line. Lets Omar and bar managers
 * spot a "stalled bar" at a glance: if a category line flatlines
 * mid-event, that\'s a signal.
 *
 * Design notes:
 *   - Compact (~140px tall) so 22 cards in a 2-column grid stay readable
 *   - No Y-axis ticks (saves horizontal space; tooltip reveals exact €)
 *   - Color palette chosen for hue separation (color-blind safe enough
 *     for "is the navy line going up" — the primary signal)
 *   - The math (buildMultiLineBarRevenuePoints) is in chart-buckets.ts;
 *     this is a thin presentational wrapper.
 *
 * Locked May 27 2026: 5 lines (4 drink categories + total). Food is
 * NOT shown as a line — bars are drink-focused per Omar; food revenue
 * still counts toward total but is invisible here. Restock alerts use
 * a different surface.
 */
import { useMemo } from 'react'

import {
  MultiLineChart,
  type SeriesSpec,
} from '@/shared/charts/MultiLineChart'
import { buildMultiLineBarRevenuePoints } from '@/features/dashboard/chart-buckets'
import { buildCategoryByProductId, type ProductLike } from '@/features/dashboard/category-resolver'
import type { StockTransactionRow } from '@/lib/mockData'


// ─── Color palette (locked May 27 2026 with Hesam) ────────────────────
// Hue-separated so each line is distinguishable in a 140px-tall chart.
const _SERIES: SeriesSpec[] = [
  { key: 'total',             name: 'Total',     color: '#1E5A8D', strokeWidth: 3 },
  { key: 'beer',              name: 'Beer',      color: '#C49A2A' },
  { key: 'cocktails',         name: 'Cocktails', color: '#C2185B' },
  { key: 'premium_cocktails', name: 'Premium',   color: '#6A1B9A' },
  { key: 'wine',              name: 'Wine',      color: '#8B0000' },
]


interface BarMiniChartProps {
  barId:        string
  transactions: StockTransactionRow[]
  products:     ProductLike[]
  eventStartMs: number
  nowMs:        number
  /** Default 140. Pass a smaller number for ultra-compact contexts. */
  height?:      number
}


export function BarMiniChart({
  barId,
  transactions,
  products,
  eventStartMs,
  nowMs,
  height = 140,
}: BarMiniChartProps) {
  // Build the (product_id -> category bucket) map once per (products) ref.
  // useMemo because products is a ~70-element array passed down from a
  // hook — recomputing the map on every render would be wasted work.
  const categoryByProductId = useMemo(
    () => buildCategoryByProductId(products),
    [products],
  )

  const data = useMemo(
    () => buildMultiLineBarRevenuePoints({
      transactions,
      barId,
      eventStartMs,
      nowMs,
      categoryByProductId,
    }),
    [transactions, barId, eventStartMs, nowMs, categoryByProductId],
  )

  // If there\'s no data (event hasn\'t started, bar has no sales), render
  // an empty placeholder so the card height stays consistent across bars.
  if (data.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-xs text-[#A0AEC0] italic"
      >
        Awaiting first sale
      </div>
    )
  }

  return (
    <MultiLineChart
      data={data}
      labelKey="time_label"
      series={_SERIES}
      height={height}
      showLegend={false}
      showYAxis={false}
    />
  )
}
