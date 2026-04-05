import { type ReactNode } from 'react'

interface KpiCardProps {
  label: string
  value: string
  delta: string
  deltaPositive: boolean
  icon: ReactNode
  color: 'blue' | 'purple' | 'red' | 'yellow'
}

const colorMap = {
  blue:   { bg: 'bg-blue-50',   icon: 'text-[#1E5A8D]',  border: 'border-blue-100' },
  purple: { bg: 'bg-purple-50', icon: 'text-[#6C63FF]',  border: 'border-purple-100' },
  red:    { bg: 'bg-red-50',    icon: 'text-[#E53E3E]',  border: 'border-red-100' },
  yellow: { bg: 'bg-yellow-50', icon: 'text-[#D69E2E]',  border: 'border-yellow-100' },
}

export function KpiCard({ label, value, delta, deltaPositive, icon, color }: KpiCardProps) {
  const c = colorMap[color]
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-[#4A5568] uppercase tracking-wide mb-2">{label}</p>
          <p className="text-3xl font-bold text-[#1A202C]">{value}</p>
        </div>
        <div className={`${c.bg} ${c.icon} p-2.5 rounded-lg border ${c.border}`}>
          {icon}
        </div>
      </div>
      <p className={`text-xs mt-3 font-medium ${deltaPositive ? 'text-[#38A169]' : 'text-[#E53E3E]'}`}>
        {delta}
      </p>
    </div>
  )
}
