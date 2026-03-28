interface BarCardProps {
  id: number
  name: string
  status: 'ok' | 'warning' | 'critical'
  revenue: string
  transactions: number
  topItem: string
  stockPct: number
}

const statusConfig = {
  ok: {
    label: 'Healthy',
    dot: 'bg-[#38A169]',
    badge: 'bg-green-50 text-[#38A169] border-green-200',
    bar: 'bg-[#38A169]',
    ring: 'ring-green-200',
  },
  warning: {
    label: 'Low Stock',
    dot: 'bg-[#D69E2E]',
    badge: 'bg-yellow-50 text-[#D69E2E] border-yellow-200',
    bar: 'bg-[#D69E2E]',
    ring: 'ring-yellow-200',
  },
  critical: {
    label: 'Critical',
    dot: 'bg-[#E53E3E] animate-pulse',
    badge: 'bg-red-50 text-[#E53E3E] border-red-200',
    bar: 'bg-[#E53E3E]',
    ring: 'ring-red-200',
  },
}

export function BarCard({ name, status, revenue, transactions, topItem, stockPct }: BarCardProps) {
  const cfg = statusConfig[status]

  return (
    <div className={`bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow ring-2 ${cfg.ring}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-[#1A202C]">{name}</h3>
          <div className="flex items-center gap-1.5 mt-1">
            <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
            <span className={`text-xs font-medium px-1.5 py-0.5 rounded-full border ${cfg.badge}`}>
              {cfg.label}
            </span>
          </div>
        </div>
        <span className="text-lg font-bold text-[#1A202C]">{revenue}</span>
      </div>

      {/* Stats */}
      <div className="space-y-2 text-sm">
        <div className="flex justify-between text-[#4A5568]">
          <span>Transactions</span>
          <span className="font-medium text-[#1A202C]">{transactions}</span>
        </div>
        <div className="flex justify-between text-[#4A5568]">
          <span>Top item</span>
          <span className="font-medium text-[#1A202C] truncate ml-2 max-w-[120px] text-right">{topItem}</span>
        </div>
      </div>

      {/* Stock bar */}
      <div className="mt-4">
        <div className="flex justify-between text-xs text-[#4A5568] mb-1">
          <span>Stock level</span>
          <span className="font-medium">{stockPct}%</span>
        </div>
        <div className="h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${cfg.bar}`}
            style={{ width: `${stockPct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
