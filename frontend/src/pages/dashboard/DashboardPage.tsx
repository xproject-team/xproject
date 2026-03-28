import { KpiCard } from '@/features/dashboard/KpiCard'
import { BarCard } from '@/features/dashboard/BarCard'

const KPI_DATA = [
  {
    label: 'Total Revenue',
    value: '€24,350',
    delta: '+12% vs last event',
    deltaPositive: true,
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    color: 'blue' as const,
  },
  {
    label: 'Transactions',
    value: '487',
    delta: '↑ 34 in last hour',
    deltaPositive: true,
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    ),
    color: 'purple' as const,
  },
  {
    label: 'Active Alerts',
    value: '3',
    delta: '2 critical, 1 warning',
    deltaPositive: false,
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
    ),
    color: 'red' as const,
  },
  {
    label: 'Stock Warnings',
    value: '7',
    delta: '3 items below threshold',
    deltaPositive: false,
    icon: (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
      </svg>
    ),
    color: 'yellow' as const,
  },
]

const BAR_DATA = [
  {
    id: 1,
    name: 'Main Bar',
    status: 'ok' as const,
    revenue: '€9,840',
    transactions: 198,
    topItem: 'Heineken',
    stockPct: 82,
  },
  {
    id: 2,
    name: 'VIP Lounge',
    status: 'warning' as const,
    revenue: '€7,120',
    transactions: 134,
    topItem: 'Moët Champagne',
    stockPct: 24,
  },
  {
    id: 3,
    name: 'Pool Bar',
    status: 'ok' as const,
    revenue: '€5,290',
    transactions: 112,
    topItem: 'Aperol Spritz',
    stockPct: 71,
  },
  {
    id: 4,
    name: 'DJ Booth',
    status: 'critical' as const,
    revenue: '€2,100',
    transactions: 43,
    topItem: 'Red Bull',
    stockPct: 8,
  },
]

export default function DashboardPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[#1A202C]">Operations Dashboard</h1>
        <p className="text-sm text-[#4A5568] mt-1">Sundance 2026 · Live event · Started 18:00</p>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {KPI_DATA.map((kpi) => (
          <KpiCard key={kpi.label} {...kpi} />
        ))}
      </div>

      {/* Bar section header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-[#1A202C]">Bar Performance</h2>
        <span className="text-xs text-[#4A5568] bg-[#F7FAFC] border border-[#E2E8F0] px-3 py-1 rounded-full">
          4 bars · Updated just now
        </span>
      </div>

      {/* Bar cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {BAR_DATA.map((bar) => (
          <BarCard key={bar.id} {...bar} />
        ))}
      </div>
    </div>
  )
}
