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
 * All of the above are overridable via axisColor/gridColor for callers
 * on a dark surface (e.g. EventRevenueChart on the Vera dashboard).
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
  /**
   * X-axis mode. 'category' (default) reads labelKey as a discrete tick
   * per row — Recharts' default behavior, unchanged from before this
   * prop existed. 'number' treats labelKey as a numeric axis (e.g. a
   * timestamp) so ticks can be explicitly controlled via xTicks/xDomain
   * instead of one tick per data row.
   */
  xAxisType?: 'category' | 'number'
  /** Explicit tick values — only used when xAxisType='number'. */
  xTicks?: number[]
  /** Axis domain — only used when xAxisType='number'. */
  xDomain?: [number | string, number | string]
  /** Formats each numeric x tick to its display label. */
  xTickFormatter?: (value: number) => string
  /** Formats the tooltip's header line. Needed when xAxisType='number' —
   *  otherwise the tooltip shows the raw numeric x value (e.g. an epoch
   *  timestamp) instead of a readable label. */
  tooltipLabelFormatter?: (value: number | string) => string
  /** Axis tick text color. Default '#4A5568' (matches the historic light theme). */
  axisColor?: string
  /** Axis tick font size in px. Default 11. */
  axisFontSize?: number
  /** Grid line color. Default '#E2E8F0'. */
  gridColor?: string
  /** Grid line stroke-opacity. Default 1 (fully opaque, historic behavior). */
  gridOpacity?: number
}


export function MultiLineChart({
  data,
  labelKey,
  series,
  height = 240,
  showLegend = true,
  showYAxis  = true,
  xAxisType  = 'category',
  xTicks,
  xDomain,
  xTickFormatter,
  tooltipLabelFormatter,
  axisColor = '#4A5568',
  axisFontSize = 11,
  gridColor = '#E2E8F0',
  gridOpacity = 1,
}: MultiLineChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsLineChart data={data} margin={{ top: 5, right: 24, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={gridColor} strokeOpacity={gridOpacity} />
        {xAxisType === 'number' ? (
          <XAxis
            dataKey={labelKey}
            type="number"
            domain={xDomain ?? ['dataMin', 'dataMax']}
            ticks={xTicks}
            tickFormatter={xTickFormatter}
            tick={{ fontSize: axisFontSize, fill: axisColor }}
          />
        ) : (
          <XAxis dataKey={labelKey} tick={{ fontSize: axisFontSize, fill: axisColor }} />
        )}
        {showYAxis && (
          <YAxis
            tick={{ fontSize: axisFontSize, fill: axisColor }}
            domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.1)]}
          />
        )}
        <Tooltip
          contentStyle={{ fontSize: 12 }}
          formatter={(value: number | string) =>
            typeof value === 'number' ? `€${value.toLocaleString()}` : value
          }
          labelFormatter={tooltipLabelFormatter}
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
