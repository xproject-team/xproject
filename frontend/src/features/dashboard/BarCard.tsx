/**
 * BarCard — one tile in the Dashboard's 2×2 grid, one per bar at the event.
 *
 * Step 7 wire-up (April 17 2026):
 * - Accepts BarKpi from features/dashboard/selectors.ts
 * - Real fields render normally: name, status, revenue, drinks sold,
 *   tier breakdown, stock level
 * - Placeholder fields (burn_rate, burn_trend, time_to_depletion_min,
 *   staff_count, last_alert) render as "—" with a subtle "soon" treatment.
 *   They'll become real once burn-rate computation, staff shifts, and
 *   alerts backends ship.
 */
import type { BarKpi, BarStatus } from '@/lib/mockData'

interface BarCardProps {
  bar: BarKpi
  onClick: (barId: string) => void
}

const STATUS_CFG: Record<BarStatus, { dot: string; label: string; labelColor: string }> = {
  healthy:  { dot: 'bg-[#38A169]',              label: 'Healthy',   labelColor: 'text-[#38A169]' },
  warning:  { dot: 'bg-[#D69E2E]',              label: 'Low Stock', labelColor: 'text-[#D69E2E]' },
  critical: { dot: 'bg-[#E53E3E] animate-pulse', label: 'Critical',  labelColor: 'text-[#E53E3E]' },
}

function stockBarColor(pct: number) {
  if (pct > 60) return 'bg-[#38A169]'
  if (pct > 30) return 'bg-[#D69E2E]'
  return 'bg-[#E53E3E]'
}

// ─── Small "not yet available" pill used by placeholder fields ──────────────
// Kept intentionally quiet — doesn't scream, but makes it obvious this number
// will become real once the relevant backend ships. One line, italicized, dim.

function Placeholder({ label }: { label: string }) {
  return (
    <span className="text-[#A0AEC0] italic" title={`${label} — coming soon`}>
      —
    </span>
  )
}

export function BarCard({ bar, onClick }: BarCardProps) {
  const cfg      = STATUS_CFG[bar.status]
  const stockPct = bar.stock_pct
  const tiers    = bar.drinks_breakdown

  const revenueEuros = Math.round(bar.revenue_cents / 100)

  return (
    <button
      onClick={() => onClick(bar.id)}
      className={[
        'rounded-xl p-5 shadow-sm hover:shadow-md transition-all text-left w-full border',
        bar.status === 'critical' ? 'bg-red-50 border-red-200' :
        bar.status === 'warning'  ? 'bg-yellow-50 border-yellow-200' :
                                    'bg-green-50/60 border-green-200',
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
          <p className="text-xl font-bold text-[#1A202C]">€{revenueEuros.toLocaleString()}</p>
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

      {/* 5 — Stock Level (REAL) */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs text-[#4A5568]">Stock Level</p>
          <p className="text-xs font-semibold text-[#1A202C]">
            {bar.current_stock}/{bar.initial_stock} units
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

      {/* 6+7+8 — Burn Rate / Time to Depletion / Staff — PLACEHOLDERS (v1.1) */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Burn Rate</p>
          <p className="text-sm font-bold mt-0.5">
            {bar.burn_rate === null ? <Placeholder label="Burn rate — no recent sales" /> : bar.burn_rate.toFixed(1)}
          </p>
          <p className="text-[9px] text-[#4A5568]">btl/hr</p>
        </div>

        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Depletion</p>
          <p className="text-sm font-bold mt-0.5">
            {bar.time_to_depletion_min === null ? <Placeholder label="Depletion — needs data" /> : bar.time_to_depletion_min < 60 ? Math.round(bar.time_to_depletion_min) + "m" : Math.floor(bar.time_to_depletion_min / 60) + "h" + (Math.round(bar.time_to_depletion_min % 60)) + "m"}
          </p>
          <p className="text-[9px] text-[#4A5568]">remaining</p>
        </div>

        <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-2 text-center">
          <p className="text-[10px] text-[#4A5568] uppercase tracking-wide">Staff</p>
          <p className="text-sm font-bold mt-0.5 flex items-center justify-center gap-0.5">
            <svg className="w-3.5 h-3.5 text-[#A0AEC0]" fill="currentColor" viewBox="0 0 20 20">
              <path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z" />
            </svg>
            <Placeholder label="Staff shift module" />
          </p>
          <p className="text-[9px] text-[#4A5568]">on shift</p>
        </div>
      </div>

      {/* 9 — Last Alert — PLACEHOLDER (v1.1 alerts backend) */}
      <div className="rounded-lg px-3 py-2 text-xs bg-[#F7FAFC] border border-[#E2E8F0] text-[#A0AEC0]">
        <span className="flex items-center gap-1.5 italic">
          <span>ⓘ</span>
          <span>Alerts feed arrives in v1.1</span>
        </span>
      </div>
    </button>
  )
}
