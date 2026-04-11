import type { Bar } from '@/lib/mockData'

interface BarCardProps {
  bar: Bar
  onClick: (barId: number) => void
}

const STATUS_CFG: Record<Bar['status'], { dot: string; label: string; labelColor: string }> = {
  healthy:  { dot: 'bg-[#38A169]',               label: 'Healthy',   labelColor: 'text-[#38A169]' },
  warning:  { dot: 'bg-[#D69E2E]',               label: 'Low Stock', labelColor: 'text-[#D69E2E]' },
  critical: { dot: 'bg-[#E53E3E] animate-pulse',  label: 'Critical',  labelColor: 'text-[#E53E3E]' },
}

function stockBarColor(pct: number) {
  if (pct > 60) return 'bg-[#38A169]'
  if (pct > 30) return 'bg-[#D69E2E]'
  return 'bg-[#E53E3E]'
}

export function BarCard({ bar, onClick }: BarCardProps) {
  const cfg      = STATUS_CFG[bar.status]
  const stockPct = Math.round((bar.current_stock / bar.initial_stock) * 100)
  const tiers    = bar.drinks_breakdown
  const critical = bar.status === 'critical'

  const trendArrow = bar.burn_trend === 'up' ? '↑' : bar.burn_trend === 'down' ? '↓' : '→'
  const trendColor =
    bar.burn_trend === 'up'   ? 'text-[#E53E3E]' :
    bar.burn_trend === 'down' ? 'text-[#38A169]' :
                                'text-[#4A5568]'

  const depletionDisplay =
    bar.time_to_depletion_min >= 60
      ? `${Math.floor(bar.time_to_depletion_min / 60)}h ${bar.time_to_depletion_min % 60}m`
      : `${bar.time_to_depletion_min}m`
  const depletionUrgent = bar.time_to_depletion_min < 45

  return (
    <button
      onClick={() => {
        console.log(`clicked bar ${bar.id}`)
        onClick(bar.id)
      }}
      className={[
        'rounded-xl p-5 shadow-sm hover:shadow-md transition-all text-left w-full',
        critical
          ? 'border border-[#E2E8F0] border-l-4 border-l-[#E53E3E] bg-red-50/40'
          : 'border border-[#E2E8F0] bg-white',
      ].join(' ')}
    >
      {/* 1+3 — Bar name + status dot + revenue */}
      <div className="flex items-start justify-between mb-1">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`} />
          <h3 className="font-bold text-[#1A202C] text-base leading-tight">{bar.name}</h3>
        </div>
        <div className="text-right shrink-0 ml-3">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Revenue</p>
          <p className="text-xl font-bold text-[#1A202C]">€{bar.revenue.toLocaleString()}</p>
        </div>
      </div>

      {/* 2 — Status label */}
      <p className={`text-xs font-semibold mb-3 ${cfg.labelColor}`}>{cfg.label}</p>

      {/* 4 — Drinks Sold */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-[#4A5568]">Drinks Sold</p>
          <p className="text-sm font-bold text-[#1A202C]">{bar.drinks_sold}</p>
        </div>
        <div className="flex gap-1">
          {(['B', 'S', 'P', 'U'] as const).map((t) => (
            <span
              key={t}
              className="text-[10px] font-semibold bg-[#F7FAFC] border border-[#E2E8F0] text-[#4A5568] px-1.5 py-0.5 rounded flex-1 text-center"
            >
              {t}:{tiers[t]}
            </span>
          ))}
        </div>
      </div>

      {/* 5 — Stock Level */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-[#4A5568]">Stock Level</p>
          <p className="text-xs font-semibold text-[#1A202C]">
            {bar.current_stock}/{bar.initial_stock} bottles
          </p>
        </div>
        <div className="h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${stockBarColor(stockPct)}`}
            style={{ width: `${stockPct}%` }}
          />
        </div>
        <p className="text-[10px] text-[#4A5568] mt-0.5">{stockPct}% remaining</p>
      </div>

      {/* 6+7+8 — Burn Rate / Time to Depletion / Staff */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Burn Rate</p>
          <p className="text-sm font-bold text-[#1A202C] mt-0.5">
            {bar.burn_rate}
            <span className={`text-xs ml-0.5 ${trendColor}`}>{trendArrow}</span>
          </p>
          <p className="text-[9px] text-[#4A5568]">btl/hr</p>
        </div>

        <div className={[
          'border rounded-lg px-2.5 py-2 text-center',
          depletionUrgent ? 'bg-red-50 border-red-200' : 'bg-[#F7FAFC] border-[#E2E8F0]',
        ].join(' ')}>
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Depletion</p>
          <p className={`text-sm font-bold mt-0.5 ${depletionUrgent ? 'text-[#E53E3E]' : 'text-[#1A202C]'}`}>
            {depletionDisplay}
          </p>
          <p className="text-[9px] text-[#4A5568]">remaining</p>
        </div>

        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Staff</p>
          <p className="text-sm font-bold text-[#1A202C] mt-0.5 flex items-center justify-center gap-0.5">
            <svg className="w-3.5 h-3.5 text-[#4A5568]" fill="currentColor" viewBox="0 0 20 20">
              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
            </svg>
            {bar.staff_count}
          </p>
          <p className="text-[9px] text-[#4A5568]">on shift</p>
        </div>
      </div>

      {/* 9 — Last Alert */}
      <div className={[
        'rounded-lg px-3 py-2 text-xs',
        bar.last_alert
          ? bar.status === 'critical'
            ? 'bg-red-50 border border-red-200 text-[#E53E3E]'
            : 'bg-yellow-50 border border-yellow-200 text-[#D69E2E]'
          : 'bg-[#F7FAFC] border border-[#E2E8F0] text-[#4A5568]',
      ].join(' ')}>
        {bar.last_alert ? (
          <span className="flex items-center gap-1.5">
            <span className="shrink-0">⚠</span>
            <span className="truncate">{bar.last_alert}</span>
          </span>
        ) : (
          <span className="flex items-center gap-1.5">
            <span className="text-[#38A169]">✓</span>
            <span>No active alerts</span>
          </span>
        )}
      </div>
    </button>
  )
}
