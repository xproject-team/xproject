/**
 * Full-menu breakdown panel for the dashboard (sits below the KPI cards).
 *
 * Reads GET /events/{id}/menu-performance and renders two columns:
 *   Drinks sold by category - each family is a header (label + subtotal),
 *     with its menu items beneath as green bars (units, incl. zero-sold)
 *   Food sold by truck - each truck is a header (name + subtotal), with its
 *     items beneath as orange bars
 *
 * Bars scale to the busiest item in each column so the comparison reads at a
 * glance. Hidden entirely until there is menu data.
 */
import type {
  DrinkFamily,
  EventMenuPerformanceDTO,
  MenuItemLineDTO,
} from '@/features/dashboard/hooks'

const DRINK_FAMILY_LABEL: Record<DrinkFamily, string> = {
  cocktails: 'Cocktails',
  beer:      'Beer',
  wine:      'Wine',
  soft:      'Soft',
  other:     'Other',
}

const DRINK_COLOR = '#2F9E6E'
const FOOD_COLOR = '#DD8C1E'

function maxUnits(items: MenuItemLineDTO[]): number {
  return items.reduce((m, i) => Math.max(m, i.units), 0)
}

interface ItemRowProps {
  name: string
  units: number
  max: number
  color: string
}

function ItemRow({ name, units, max, color }: ItemRowProps) {
  const pct = max > 0 ? Math.round((units / max) * 100) : 0
  return (
    <div className="flex items-center gap-3 py-0.5">
      <span className="w-36 shrink-0 truncate text-sm text-[#1A202C]" title={name}>
        {name}
      </span>
      <div className="flex-1 h-2 rounded-full bg-[#EDF2F7] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-10 text-right text-sm font-semibold text-[#1A202C] tabular-nums">
        {units}
      </span>
    </div>
  )
}

interface KpiBreakdownPanelProps {
  menu: EventMenuPerformanceDTO | null
}

export function KpiBreakdownPanel({ menu }: KpiBreakdownPanelProps) {
  if (!menu) return null
  const { drinks, food } = menu
  if (drinks.length === 0 && food.length === 0) return null

  const drinkMax = maxUnits(drinks.flatMap((g) => g.items))
  const foodMax = maxUnits(food.flatMap((g) => g.items))

  return (
    <div className="px-5 pt-4 bg-[#F7FAFC] shrink-0">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-5">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-6">

          {/* Drinks sold by category */}
          <div>
            <h2 className="text-sm font-semibold text-[#4A5568] mb-3">
              Drinks sold by category
            </h2>
            {drinks.length === 0 ? (
              <p className="text-xs text-[#A0AEC0]">No drinks on the menu.</p>
            ) : (
              drinks.map((g) => (
                <div key={g.family} className="mb-3 last:mb-0">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-[11px] font-bold uppercase tracking-widest text-[#A0AEC0]">
                      {DRINK_FAMILY_LABEL[g.family]}
                    </span>
                    <span className="text-xs font-bold text-[#1A202C] tabular-nums">
                      {g.subtotal_units}
                    </span>
                  </div>
                  {g.items.map((i) => (
                    <ItemRow
                      key={i.product_id}
                      name={i.product_name}
                      units={i.units}
                      max={drinkMax}
                      color={DRINK_COLOR}
                    />
                  ))}
                </div>
              ))
            )}
          </div>

          {/* Food sold by truck */}
          <div>
            <h2 className="text-sm font-semibold text-[#4A5568] mb-3">
              Food sold by truck
            </h2>
            {food.length === 0 ? (
              <p className="text-xs text-[#A0AEC0]">No food trucks on the menu.</p>
            ) : (
              food.map((g) => (
                <div key={g.bar_id} className="mb-3 last:mb-0">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-[11px] font-bold uppercase tracking-widest text-[#A0AEC0]">
                      {g.bar_name}
                    </span>
                    <span className="text-xs font-bold text-[#1A202C] tabular-nums">
                      {g.subtotal_units}
                    </span>
                  </div>
                  {g.items.map((i) => (
                    <ItemRow
                      key={i.product_id}
                      name={i.product_name}
                      units={i.units}
                      max={foodMax}
                      color={FOOD_COLOR}
                    />
                  ))}
                </div>
              ))
            )}
          </div>

        </div>
      </div>
    </div>
  )
}
