/**
 * EventRevenueChart — big top-of-dashboard chart.
 *
 * Shows event-total cumulative revenue:
 *   - Actual (solid navy): live event-total, summed across ALL bars,
 *                          cumulative over hour buckets
 *   - ML Predicted (dashed purple): placeholder until MLPredictor
 *                                   lands in Phase 2 resumption.
 *                                   For now data[i].predicted is null
 *                                   on every point and Recharts renders
 *                                   a flat empty line — clean enough.
 *
 * Sized for ~2 bar cards wide. Caller controls grid placement.
 *
 * Design (locked May 27 2026 with Hesam):
 *   - Event-TOTAL, not per-bar (per-bar charts live inside bar cards)
 *   - Goal: "are we beating our prediction tonight?" at a glance
 *   - When MLPredictor ships: data[i].predicted gets real numbers and
 *     the dashed line becomes meaningful. Zero code change here.
 */
import { useMemo } from 'react'

import {
  MultiLineChart,
  type SeriesSpec,
} from '@/shared/charts/MultiLineChart'
import { buildEventRevenuePoints } from '@/features/dashboard/chart-buckets'
import type { StockTransactionRow } from '@/lib/mockData'


// Two-line spec. Order matters for Recharts: "actual" drawn first
// underneath, "predicted" overlays. Both use the same color tokens as
// the original overlay chart for visual continuity.
const _SERIES: SeriesSpec[] = [
  {
    key:         'actual',
    name:        'Actual (live)',
    color:       '#1E5A8D',
    strokeWidth: 3,
  },
  {
    key:         'predicted',
    name:        'ML Predicted',
    color:       '#6C63FF',
    strokeWidth: 2,
    dashed:      true,
  },
]


interface EventRevenueChartProps {
  /** Transactions across ALL bars in the event. */
  transactions: StockTransactionRow[]
  eventStartMs: number
  nowMs:        number
  /** Chart height in px. Default 240 (matches existing LineChart default). */
  height?:      number
}


export function EventRevenueChart({
  transactions,
  eventStartMs,
  nowMs,
  height = 240,
}: EventRevenueChartProps) {
  const data = useMemo(
    () => buildEventRevenuePoints({ transactions, eventStartMs, nowMs }),
    [transactions, eventStartMs, nowMs],
  )

  if (data.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center text-sm text-[#A0AEC0] italic
                    border border-[#E2E8F0] rounded-lg bg-white"
      >
        Awaiting first transaction
      </div>
    )
  }

  return (
    <div className="border border-[#E2E8F0] rounded-lg bg-white p-4 shadow-sm">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold text-[#2E4B7A]">
          Event Revenue
        </h2>
        <span className="text-xs text-[#A0AEC0]">
          Actual vs ML Predicted
        </span>
      </div>
      <MultiLineChart
        data={data}
        labelKey="time_label"
        series={_SERIES}
        height={height}
        showLegend={true}
        showYAxis={true}
      />
    </div>
  )
}
