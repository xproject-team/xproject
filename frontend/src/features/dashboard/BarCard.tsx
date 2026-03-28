/**
 * BarCard — compact summary card for a single bar showing key stock and sales metrics.
 */
export interface BarSummary {
  id: number
  name: string
  salesVelocity: number
  stockHealth: 'ok' | 'low' | 'critical'
  alertCount: number
}

interface BarCardProps {
  bar: BarSummary
}

export function BarCard({ bar }: BarCardProps) {
  const healthColor = {
    ok: 'text-[#38A169]',
    low: 'text-[#D69E2E]',
    critical: 'text-[#E53E3E]',
  }[bar.stockHealth]

  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-4">
      <h3 className="font-semibold text-[#1A202C]">{bar.name}</h3>
      <p className={`text-sm font-medium ${healthColor}`}>{bar.stockHealth.toUpperCase()}</p>
      {bar.alertCount > 0 && (
        <span className="text-xs bg-[#E53E3E] text-white px-2 py-0.5 rounded-full">
          {bar.alertCount} alert{bar.alertCount > 1 ? 's' : ''}
        </span>
      )}
    </div>
  )
}
