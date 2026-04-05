/**
 * BarChart — Recharts wrapper for categorical comparisons (e.g. per-bar sales totals).
 */
import {
  Bar,
  BarChart as RechartsBarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface DataPoint {
  label: string
  value: number
}

interface BarChartProps {
  data: DataPoint[]
  height?: number
  color?: string
}

export function BarChart({ data, height = 240, color = '#1E5A8D' }: BarChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RechartsBarChart data={data} margin={{ top: 5, right: 16, bottom: 5, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#4A5568' }} />
        <YAxis tick={{ fontSize: 11, fill: '#4A5568' }} />
        <Tooltip />
        <Bar dataKey="value" fill={color} radius={[3, 3, 0, 0]} />
      </RechartsBarChart>
    </ResponsiveContainer>
  )
}
