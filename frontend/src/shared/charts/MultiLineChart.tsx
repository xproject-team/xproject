/**
 * MultiLineChart — Recharts wrapper for charts with N parallel series.
 *
 * Generic counterpart to LineChart (which renders one "value" + an
 * optional "forecast"). MultiLineChart takes a SeriesSpec[] and renders
 * one Line per spec. The data shape is row-oriented: each point is a
 * record with one key per series (plus a labelKey for the x-axis).
 *
 * Per-series styling (color, stroke width, dashed) lives in the caller's
 * SeriesSpec[]. Keeps this wrapper purely structural — no palette
 * decisions baked in, so it can be reused by BarMiniChart, by
 * EventRevenueChart, or by future N-line charts.
 *
 * Style conventions mirror LineChart.tsx:
 *   grid #E2E8F0 / tick #4A5568 / dotless lines / responsive container.
 */
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'


export interface SeriesSpec {
  /** Key on each datum to read this series' value from. */
  key:          string
  /** Human-readable label for legend + tooltip. */
  name:         string
  /** Stroke color (any CSS color). */
  color:        string
  /** Line thickness in pixels. Default 2. */
  strokeWidth?: number
  /** Render as dashed instead of solid. Default false. */
  dashed?:      boolean
}


interface MultiLineChartProps {
  /** Row-oriented data. We accept `readonly object[]` so callers can
   *  pass typed interfaces (MultiLineChartPoint, ChartPoint, etc.)
   *  without widening; Recharts only does runtime key access at the
   *  series.key path, so the structural typing here doesn't need to
   *  match every field. */
  data:      object[]
  /** Which datum key holds the x-axis label. */
  labelKey:  string
  /** One spec per line to render. */
  series:    SeriesSpec[]
  /** Chart height in px. Default 240. Use ~120 for bar-card mini-charts. */
  height?:   number
  /** Show the legend below the chart? Default true. */
  showLegend?: boolean
  /** Show Y-axis ticks? Default true. Set false for ultra-compact mini-charts. */
  showYAxis?:  boolean
}


export function MultiLineChart({
  data,
  labelKey,
  series,
  height = 240,
  showLegend = true,
  showYAxis  = true,
}: MultiLineChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsLineChart data={data} margin={{ top: 5, right: 16, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
        <XAxis dataKey={labelKey} tick={{ fontSize: 11, fill: '#4A5568' }} />
        {showYAxis && (
          <YAxis tick={{ fontSize: 11, fill: '#4A5568' }} />
        )}
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          formatter={(value: number | string) =>
            typeof value === 'number' ? `€${value.toLocaleString()}` : value
          }
        />
        {showLegend && (
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} iconSize={10} />
        )}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name}
            stroke={s.color}
            strokeWidth={s.strokeWidth ?? 2}
            strokeDasharray={s.dashed ? '4 2' : undefined}
            dot={false}
            isAnimationActive={false}
            connectNulls={true}
          />
        ))}
      </RechartsLineChart>
    </ResponsiveContainer>
  )
}
