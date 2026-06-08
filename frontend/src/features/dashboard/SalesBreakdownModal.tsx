/**
 * Sales breakdown modal — opens when Omar taps the Drinks or Food KPI card.
 *
 * Shows the full menu performance (GET /events/{id}/menu-performance):
 *   Drinks sold by category  -> green item bars under each family header
 *   Food sold by truck       -> orange item bars under each truck header
 *
 * Keeps the main dashboard uncluttered; details live here on demand.
 */
import { useEffect } from 'react'

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
      <span className="w-36 shrink-0 truncate text-sm text-[#1A202C]" title={name}>{name}</span>
      <div className="flex-1 h-2 rounded-full bg-[#EDF2F7] overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="w-10 text-right text-sm font-semibold text-[#1A202C] tabular-nums">{units}</span>
    </div>
  )
}

interface SalesBreakdownModalProps {
  menu: EventMenuPerformanceDTO | null
  open: boolean
  onClose: () => void
}

export function SalesBreakdownModal({ menu, open, onClose }: SalesBreakdownModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const drinks = menu?.drinks ?? []
  const food = menu?.food ?? []
  const drinkMax = maxUnits(drinks.flatMap((g) => g.items))
  const foodMax = maxUnits(food.flatMap((g) => g.items))
  const hasData = drinks.length > 0 || food.length > 0

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E2E8F0] sticky top-0 bg-white rounded-t-2xl">
          <h2 className="text-base font-bold text-[#1A202C]">Sales breakdown</h2>
          <button
            onClick={onClose}
            className="text-[#A0AEC0] hover:text-[#1A202C] text-2xl leading-none px-1"
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <div className="p-6">
          {!hasData ? (
            <p className="text-sm text-[#A0AEC0]">No sales yet.</p>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-6">

              {/* Drinks sold by category */}
              <div>
                <h3 className="text-sm font-semibold text-[#4A5568] mb-3">Drinks sold by category</h3>
                {drinks.length === 0 ? (
                  <p className="text-xs text-[#A0AEC0]">No drinks on the menu.</p>
                ) : (
                  drinks.map((g) => (
                    <div key={g.family} className="mb-3 last:mb-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-bold uppercase tracking-widest text-[#A0AEC0]">
                          {DRINK_FAMILY_LABEL[g.family]}
                        </span>
                        <span className="text-xs font-bold text-[#1A202C] tabular-nums">{g.subtotal_units}</span>
                      </div>
                      {g.items.map((i) => (
                        <ItemRow key={i.product_id} name={i.product_name} units={i.units} max={drinkMax} color={DRINK_COLOR} />
                      ))}
                    </div>
                  ))
                )}
              </div>

              {/* Food sold by truck */}
              <div>
                <h3 className="text-sm font-semibold text-[#4A5568] mb-3">Food sold by truck</h3>
                {food.length === 0 ? (
                  <p className="text-xs text-[#A0AEC0]">No food trucks on the menu.</p>
                ) : (
                  food.map((g) => (
                    <div key={g.bar_id} className="mb-3 last:mb-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-bold uppercase tracking-widest text-[#A0AEC0]">
                          {g.bar_name}
                        </span>
                        <span className="text-xs font-bold text-[#1A202C] tabular-nums">{g.subtotal_units}</span>
                      </div>
                      {g.items.map((i) => (
                        <ItemRow key={i.product_id} name={i.product_name} units={i.units} max={foodMax} color={FOOD_COLOR} />
                      ))}
                    </div>
                  ))
                )}
              </div>

            </div>
          )}
        </div>
      </div>
    </div>
  )
}
