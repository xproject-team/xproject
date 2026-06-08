/**
 * Compact horizontal breakdown chips for the dashboard top strip.
 *
 * Sits directly below KpiStrip. Reads the same GET /events/{id}/kpi-summary
 * payload and shows two chip groups:
 *   Drinks - by family (cocktails / beer / wine / soft / other)
 *   Food   - by FoodType (burgers / sandwiches / ... / other)
 *
 * Each chip: {label} {units} · {revenue}. Drink revenue is 100% Omar; food
 * chips show GROSS per type (the partnership share is applied in the Food
 * KPI card above). Only families/types with sales appear (the endpoint omits
 * empty ones); the whole bar hides until there is data.
 */
import type { DrinkFamily, EventKpiSummaryDTO } from '@/features/dashboard/hooks'

function formatEur(eur: string | number): string {
  const n = typeof eur === 'string' ? parseFloat(eur) : eur
  return `€${(Number.isFinite(n) ? n : 0).toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`
}

const DRINK_FAMILY_LABEL: Record<DrinkFamily, string> = {
  cocktails: 'Cocktails',
  beer:      'Beer',
  wine:      'Wine',
  soft:      'Soft',
  other:     'Other',
}

function titleCase(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1)
}

const CHIP =
  'text-[11px] font-semibold bg-[#F7FAFC] border border-[#E2E8F0] ' +
  'text-[#4A5568] px-2 py-0.5 rounded whitespace-nowrap shrink-0'
const GROUP_LABEL =
  'text-[10px] font-bold uppercase tracking-widest text-[#A0AEC0] mr-1 shrink-0'

interface KpiBreakdownPanelProps {
  kpi: EventKpiSummaryDTO | null
}

export function KpiBreakdownPanel({ kpi }: KpiBreakdownPanelProps) {
  if (!kpi) return null
  const drinks = kpi.drinks.by_category
  const food = kpi.food.by_type
  if (drinks.length === 0 && food.length === 0) return null

  return (
    <div className="bg-white border-b border-[#E2E8F0] px-5 py-2 flex items-center gap-2 overflow-x-auto shrink-0">
      {drinks.length > 0 && (
        <>
          <span className={GROUP_LABEL}>Drinks</span>
          {drinks.map((d) => (
            <span key={`drink-${d.family}`} className={CHIP}>
              {DRINK_FAMILY_LABEL[d.family]}{' '}
              <span className="text-[#1A202C]">{d.units}</span>
              {' · '}
              {formatEur(d.revenue_eur)}
            </span>
          ))}
        </>
      )}

      {drinks.length > 0 && food.length > 0 && (
        <span className="h-4 w-px bg-[#E2E8F0] mx-2 shrink-0" />
      )}

      {food.length > 0 && (
        <>
          <span className={GROUP_LABEL}>Food</span>
          {food.map((f) => (
            <span key={`food-${f.food_type}`} className={CHIP}>
              {titleCase(f.food_type)}{' '}
              <span className="text-[#1A202C]">{f.units}</span>
              {' · '}
              {formatEur(f.revenue_eur)}
            </span>
          ))}
        </>
      )}
    </div>
  )
}
