/**
 * Sales breakdown modal — opens when Omar taps the Drinks or Food KPI card.
 *
 * Shows the full menu performance (GET /events/{id}/menu-performance):
 *   Drinks sold by category  -> categorical-palette item bars per family
 *   Food sold by truck       -> cyan item bars under each truck header
 *
 * Keeps the main dashboard uncluttered; details live here on demand.
 */
import { useEffect } from 'react'

import type {
  DrinkFamily,
  EventMenuPerformanceDTO,
  MenuItemLineDTO,
} from '@/features/dashboard/hooks'
import { colorForCategory } from '@/design-system/categoricalPalette'
import { EmptyState } from '@/design-system/components'
import '@/design-system/components/components.css'

const DRINK_FAMILY_LABEL: Record<DrinkFamily, string> = {
  cocktails: 'Cocktails',
  beer:      'Beer',
  wine:      'Wine',
  soft:      'Soft',
  other:     'Other',
}

const FOOD_COLOR = 'var(--v-cyan)'

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
  const isZero = units === 0
  const textColor = isZero ? 'var(--v-text-dim)' : 'var(--v-text)'
  return (
    <div className="flex items-center gap-3 py-0.5">
      <span className="w-36 shrink-0 truncate text-[13px]" style={{ color: textColor }} title={name}>{name}</span>
      <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: 'var(--v-surface-raised)' }}>
        {!isZero && (
          <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
        )}
      </div>
      <span className="w-10 text-right text-sm font-medium tabular-nums" style={{ color: textColor }}>{units}</span>
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
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(8,9,13,0.72)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }}
      onClick={onClose}
    >
      <div
        className="max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div
          className="flex items-center justify-between px-6 py-4 sticky top-0"
          style={{ borderBottom: '0.5px solid var(--v-border)', background: 'var(--v-surface-raised)', borderRadius: 'var(--v-radius-lg) var(--v-radius-lg) 0 0' }}
        >
          <h2 className="text-base font-medium" style={{ color: 'var(--v-text)' }}>Sales breakdown</h2>
          <button
            onClick={onClose}
            className="text-2xl leading-none px-1 transition-colors"
            style={{ color: 'var(--v-text-muted)' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-text)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-muted)')}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <div className="p-6">
          {!hasData ? (
            <EmptyState headline="No sales yet" body="No sales yet." />
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-6">

              {/* Drinks sold by category */}
              <div>
                <h3 className="text-[14px] font-medium mb-3" style={{ color: 'var(--v-text)' }}>Drinks sold by category</h3>
                {drinks.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--v-text-dim)' }}>No drinks on the menu.</p>
                ) : (
                  drinks.map((g) => (
                    <div key={g.family} className="mb-3 last:mb-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>
                          {DRINK_FAMILY_LABEL[g.family]}
                        </span>
                        <span className="text-xs font-medium tabular-nums" style={{ color: 'var(--v-text)' }}>{g.subtotal_units}</span>
                      </div>
                      {g.items.map((i) => (
                        <ItemRow key={i.product_id} name={i.product_name} units={i.units} max={drinkMax} color={colorForCategory(g.family)} />
                      ))}
                    </div>
                  ))
                )}
              </div>

              {/* Food sold by truck */}
              <div>
                <h3 className="text-[14px] font-medium mb-3" style={{ color: 'var(--v-text)' }}>Food sold by truck</h3>
                {food.length === 0 ? (
                  <p className="text-xs" style={{ color: 'var(--v-text-dim)' }}>No food trucks on the menu.</p>
                ) : (
                  food.map((g) => (
                    <div key={g.bar_id} className="mb-3 last:mb-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>
                          {g.bar_name}
                        </span>
                        <span className="text-xs font-medium tabular-nums" style={{ color: 'var(--v-text)' }}>{g.subtotal_units}</span>
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
