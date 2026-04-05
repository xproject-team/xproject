/**
 * LineChart — Recharts wrapper for time-series data.
 * Feature components pass typed data; this component handles all Recharts config.
 */
import {
  CartesianGrid,
  Line,
  LineChart as RechartsLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface DataPoint {
  label: string
  value: number
  forecast?: number
}

interface LineChartProps {
  data: DataPoint[]
  height?: number
}

export function LineChart({ data, height = 240 }: LineChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsLineChart data={data} margin={{ top: 5, right: 16, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#4A5568' }} />
        <YAxis tick={{ fontSize: 11, fill: '#4A5568' }} />
        <Tooltip />
        <Line type="monotone" dataKey="value" stroke="#1E5A8D" strokeWidth={2} dot={false} />
        {data.some((d) => d.forecast !== undefined) && (
          <Line
            type="monotone"
            dataKey="forecast"
            stroke="#6C63FF"
            strokeWidth={2}
            strokeDasharray="4 2"
            dot={false}
          />
        )}
      </RechartsLineChart>
    </ResponsiveContainer>
  )
}
