/**
 * ChargeBarsPage — pre-event warehouse → bar dispatch (Chunk 3b).
 *
 * T-1 hour before doors open, Omar walks to each bar and "charges" it
 * with bottles from the warehouse. One card per drinks/food/service
 * bar (recharge bars skipped — they don't sell anything). Each card's
 * "Charge" click fires one dispatch POST per pending row through the
 * SAME EventStockBarAllocation pipeline Chunk 2 already wired into
 * the Dashboard bar card + depletion alerts (see useChargeBars.ts).
 *
 * Route: /events/:event_id/charge-bars
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { useEvent } from '@/features/events/hooks'
import { useBars } from '@/features/bars/hooks'
import { useSupplierProducts } from '@/features/event_storage/hooks'
import { ChargeBarCard } from './ChargeBarCard'

export default function ChargeBarsPage() {
  // Phase 1 restructure: nested under the /events/:id/* layout route,
  // which declares the param as :id (not :event_id).
  const { id: event_id } = useParams<{ id: string }>()
  const eventQuery = useEvent(event_id)
  const barsQuery = useBars(event_id)
  const supplierProductsQuery = useSupplierProducts()

  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 3500)
    return () => window.clearTimeout(t)
  }, [toast])

  const event = eventQuery.data
  const isReadOnly = event?.status === 'completed'
  // BarType (lib/mockData.ts) doesn't list 'recharge' even though real bar
  // rows use it (see wizard's BarDraft.bar_type) — cast to string so this
  // runtime-valid comparison isn't rejected by the stale type alias.
  const chargeableBars = (barsQuery.data ?? []).filter(
    (b) => (b.bar_type as string) !== 'recharge',
  )

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[#1A202C]">
          Charge Bars{event ? ` — ${event.name}` : ''}
        </h1>
        <p className="text-sm text-[#4A5568] mt-1">
          Move bottles from the warehouse to each bar before the event starts.
          Every action logs to the activity feed.
        </p>
      </div>

      {isReadOnly && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-sm text-amber-900">
            Event is completed — no more charges.
          </p>
        </div>
      )}

      {(eventQuery.isLoading || barsQuery.isLoading) ? (
        <p className="text-sm text-[#A0AEC0]">Loading…</p>
      ) : chargeableBars.length === 0 ? (
        <p className="text-sm text-[#A0AEC0]">No bars configured for this event yet.</p>
      ) : (
        <div className="space-y-4">
          {chargeableBars.map((bar) => (
            <ChargeBarCard
              key={bar.id}
              bar={bar}
              eventId={event_id ?? ''}
              supplierProducts={supplierProductsQuery.data ?? []}
              readOnly={isReadOnly}
              onToast={setToast}
            />
          ))}
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-6 bg-[#1A202C] text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}
