/**
 * hydrate.ts — map FullEventDetail (GET /events/{id}/full) → WizardState.
 *
 * Only called in edit mode by EventWizardPage. Populates WizardState so
 * the wizard's step components render the existing event, and stashes
 * the untouched-by-wizard data (Slesh basics, products/menu/allocations)
 * in _loaded_event + _hydration for Chunk 3b's payload mapper to merge
 * back into the PUT.
 *
 * The critical guard against data corruption: WizardState carries only
 * ~8 of ~15 event basics and ZERO product-editing UI. Without this
 * passthrough, an edit-save would null out stripe_ragione_sociale,
 * wristband_qty_per_type, refund_*, and (worse) drop the entire menu
 * and starting allocations because the payload mapper emits products=[]
 * / menu=[] / allocations=[] when parsed_plan is null.
 */
import type { FullEventDetail } from '@/features/events/useFullEvent'
import { buildEmptyWizardState, type BarDraft, type WizardState } from './types'

/** Convert a backend ISO datetime into the value <input type="datetime-local">
 *  expects: YYYY-MM-DDTHH:mm, in the browser's local timezone. */
function toDatetimeLocal(iso: string): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

export function hydrateWizardState(data: FullEventDetail): WizardState {
  const empty = buildEmptyWizardState()
  const { event, bars, products, menu, allocations } = data

  const barDrafts: BarDraft[] = bars.map((b, index) => ({
    client_id: crypto.randomUUID(),
    name: b.name,
    device_count: b.device_count,
    bar_type: (b.bar_type as BarDraft['bar_type']) ?? 'drinks',
    slesh_shop_id: b.slesh_negozio_id ?? null,
    from_excel: null,
    hydration_bar_index: index,
  }))

  const rechargeDeviceCount = barDrafts
    .filter((b) => b.bar_type === 'recharge')
    .reduce((sum, b) => sum + b.device_count, 0)

  return {
    ...empty,
    name: event.name,
    scheduled_at: toDatetimeLocal(event.scheduled_at),
    scheduled_end_at: toDatetimeLocal(event.scheduled_end_at),
    venue_id: event.venue.id,
    expected_guest_count: event.expected_guest_count,
    food_revenue_share_pct: event.food_revenue_share_pct ?? 30,
    parsed_plan: null,
    picked_date: null,
    bars: barDrafts,
    recharge_device_count: rechargeDeviceCount,
    topup_denominations_user: event.topup_denominations_user ?? [],
    topup_denominations_staff: event.topup_denominations_staff ?? [],
    current_step: 1,
    is_dirty: false,
    event_id: event.id,
    _loaded_event: event,
    _hydration: { products, menu, allocations },
  }
}
