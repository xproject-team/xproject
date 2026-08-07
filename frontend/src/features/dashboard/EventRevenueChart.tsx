/**
 * EventRevenueChart — big top-of-dashboard chart.
 *
 * Shows event-total cumulative revenue:
 *   - Actual (solid cyan): live event-total, summed across ALL bars,
 *                          cumulative over hour buckets
 *   - ML Predicted (dashed violet): real values from the Phase D
 *                                   nowcast endpoint (see
 *                                   useRevenueForecast), merged onto
 *                                   the chart's buckets by
 *                                   mergePredictedCurve. Buckets
 *                                   before "now" stay null — the
 *                                   actual line already covers those.
 *
 * Sized for ~2 bar cards wide. Caller controls grid placement.
 *
 * Design (locked May 27 2026 with Hesam):
 *   - Event-TOTAL, not per-bar (per-bar charts live inside bar cards)
 *   - Goal: "are we beating our prediction tonight?" at a glance
 *
 * X-axis (Day 3 restyle): ticks are derived from the actual time RANGE
 * of the data (min/max time_ms), not from row count — a sparse event
 * with only 1-2 buckets no longer repeats the same label across the
 * whole axis width. Targets 6-8 evenly spaced, deduplicated ticks.
 */
import { useMemo } from 'react'

import {
  MultiLineChart,
  type SeriesSpec,
} from '@/shared/charts/MultiLineChart'
import { buildEventRevenuePoints, mergePredictedCurve, type ChartPoint } from '@/features/dashboard/chart-buckets'
import type { StockTransactionRow } from '@/lib/mockData'
import type { PredictedCurvePoint } from '@/features/predictions/useRevenueForecast'
import { EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'


// Two-line spec. Order matters for Recharts: "actual" drawn first
// underneath, "predicted" overlays. Cyan = actual/live data, violet =
// prediction — the Vera design system's chart-color convention.
const _SERIES: SeriesSpec[] = [
  {
    key:         'actual',
    name:        'Actual (live)',
    color:       'var(--v-cyan)',
    strokeWidth: 2,
  },
  {
    key:         'predicted',
    name:        'ML Predicted',
    color:       'var(--v-violet)',
    strokeWidth: 2,
    dashed:      true,
  },
]

function formatHM(ms: number): string {
  const d = new Date(ms)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

/**
 * Derive evenly-spaced x-axis tick VALUES from the actual time range of
 * the data (first bucket -> last bucket), independent of how many rows
 * exist. Targets `targetCount` ticks, deduplicated by rendered label so
 * a short/sparse window never repeats the same "HH:MM" twice.
 */
function deriveTimeTicks(points: ChartPoint[], targetCount = 7): number[] {
  if (points.length === 0) return []
  const minMs = points[0].time_ms
  const maxMs = points[points.length - 1].time_ms
  if (minMs === maxMs) return [minMs]

  const ticks: number[] = []
  const seenLabels = new Set<string>()
  for (let i = 0; i < targetCount; i++) {
    const ms = Math.round(minMs + ((maxMs - minMs) * i) / (targetCount - 1))
    const label = formatHM(ms)
    if (seenLabels.has(label)) continue
    seenLabels.add(label)
    ticks.push(ms)
  }
  return ticks
}


interface EventRevenueChartProps {
  /** Transactions across ALL bars in the event. */
  transactions: StockTransactionRow[]
  eventStartMs: number
  nowMs:        number
  /** Chart height in px. Default 240 (matches existing LineChart default). */
  height?:      number
  /**
   * Phase D forecast inputs, all optional — omit any of the three (or
   * pass predictedCurve=[]) and the chart falls back to the pre-Phase-E
   * behavior (predicted stays null on every point). See
   * mergePredictedCurve in chart-buckets.ts for the merge algorithm.
   */
  predictedCurve?:      PredictedCurvePoint[]
  currentRevenueEur?:   number
  hourOffsetFromStart?: number
}


export function EventRevenueChart({
  transactions,
  eventStartMs,
  nowMs,
  height = 240,
  predictedCurve,
  currentRevenueEur,
  hourOffsetFromStart,
}: EventRevenueChartProps) {
  const data = useMemo(() => {
    const points = buildEventRevenuePoints({ transactions, eventStartMs, nowMs })
    return mergePredictedCurve(points, predictedCurve, eventStartMs, currentRevenueEur, hourOffsetFromStart)
  }, [transactions, eventStartMs, nowMs, predictedCurve, currentRevenueEur, hourOffsetFromStart])

  const ticks = useMemo(() => deriveTimeTicks(data), [data])

  if (data.length === 0) {
    return (
      <div className="v-card p-4 h-full flex items-center justify-center" style={{ minHeight: height }}>
        <EmptyState
          headline="Awaiting first transaction"
          body="Revenue will appear once orders start streaming in from Slesh POS."
        />
      </div>
    )
  }

  return (
    <div className="v-card p-4 h-full">
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-[11px] font-semibold tracking-wide uppercase" style={{ color: 'var(--v-text-muted)' }}>
          Event Revenue
        </span>
        <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
          Actual vs ML Predicted
        </span>
      </div>
      <MultiLineChart
        data={data}
        labelKey="time_ms"
        series={_SERIES}
        height={height}
        showLegend={true}
        showYAxis={true}
        xAxisType="number"
        xTicks={ticks}
        xDomain={[data[0].time_ms, data[data.length - 1].time_ms]}
        xTickFormatter={formatHM}
        tooltipLabelFormatter={(v) => formatHM(Number(v))}
        axisColor="var(--v-text-dim)"
        axisFontSize={10}
        gridColor="var(--v-border)"
        gridOpacity={0.5}
      />
    </div>
  )
}
