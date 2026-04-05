/**
 * StatsStrip — horizontal strip of high-level event KPIs (total sales, active alerts, etc.).
 */
interface Stat {
  label: string
  value: string | number
}

interface StatsStripProps {
  stats?: Stat[]
}

const DEFAULT_STATS: Stat[] = [
  { label: 'Total Sales', value: '—' },
  { label: 'Active Alerts', value: '—' },
  { label: 'Items Low Stock', value: '—' },
  { label: 'Tickets Scanned', value: '—' },
]

export function StatsStrip({ stats = DEFAULT_STATS }: StatsStripProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {stats.map((stat) => (
        <div key={stat.label} className="bg-white border border-[#E2E8F0] rounded-lg p-4">
          <p className="text-xs text-[#4A5568] uppercase tracking-wide">{stat.label}</p>
          <p className="text-2xl font-bold text-[#1A202C] mt-1">{stat.value}</p>
        </div>
      ))}
    </div>
  )
}
