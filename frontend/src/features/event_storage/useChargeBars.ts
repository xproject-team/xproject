/**
 * useChargeBarDispatch — Chunk 3b "Charge Bars" per-row dispatch.
 *
 * Thin wrapper around POST /event-storage/allocations — the SAME
 * single-dispatch endpoint useCreateDispatch (hooks.ts) already calls.
 * Chunk 2 wired this table (EventStockBarAllocation) into the Dashboard
 * bar card's stock section + depletion alerts via
 * bar_supplier_stock_service.py, so charging through it is what
 * actually makes "Charge Bars" visible on the bar card — the
 * warehouse module's own DISPATCH scan (warehouse_allocations,
 * Product-keyed) is a separate, unconnected system that does NOT
 * feed the bar card.
 *
 * Fired once PER PENDING ROW from the UI (not the atomic
 * /allocations/bulk endpoint), so a batch of N charges can partially
 * succeed — a bad row doesn't roll back the good ones in the same
 * click.
 *
 * Idempotency note: EventStockBarAllocation is intentionally
 * history-preserving with no unique constraint (every dispatch is a
 * new row — see the model docstring). There is no server-side
 * idempotency key here, unlike the warehouse module's client_event_id
 * dedup. Protection against an accidental double-submit is therefore
 * front-end only: ChargeBarCard disables its "Charge" button while a
 * request for that bar is in flight.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { eventStorageKeys } from './hooks'
import type { DispatchCreate, DispatchResponse } from './types'

export function useChargeBarDispatch(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: DispatchCreate): Promise<DispatchResponse> => {
      const { data } = await api.post<DispatchResponse>(
        `/event-storage/allocations?event_id=${eventId}`,
        payload,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: eventStorageKeys.summaryForEvent(eventId) })
      qc.invalidateQueries({ queryKey: eventStorageKeys.byBarForEvent(eventId) })
      qc.invalidateQueries({ queryKey: ['event-storage', 'activity', eventId] })
      // Dashboard's useBarSupplierStock query key (features/dashboard/hooks.ts).
      // Invalidating the 3-element prefix matches all bar_id variants.
      qc.invalidateQueries({ queryKey: ['events', eventId, 'bar-supplier-stock'] })
    },
  })
}
