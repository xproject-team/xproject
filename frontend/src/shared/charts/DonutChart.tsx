/**
 * DonutChart — Recharts wrapper for proportional breakdowns (e.g. stock composition).
 */
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

interface Slice {
  label: string
  value: number
  color?: string
}

const DEFAULT_COLORS = ['#1E5A8D', '#6C63FF', '#38A169', '#D69E2E', '#E53E3E']

interface DonutChartProps {
  data: Slice[]
  size?: number
}

export function DonutChart({ data, size = 200 }: DonutChartProps) {
  return (
    <ResponsiveContainer width="100%" height={size}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          innerRadius={size * 0.3}
          outerRadius={size * 0.45}
        >
          {data.map((entry, i) => (
            <Cell key={entry.label} fill={entry.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip />
      </PieChart>
    </ResponsiveContainer>
  )
}
