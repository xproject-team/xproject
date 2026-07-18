/**
 * "Map Slesh shop to a bar" modal — Jul-19 sprint phantom-bar fix.
 *
 * Opened by the "Map to bar" button on an alert card with alert_type=
 * 'system' and context_json.category='unmapped_shop' (see DashboardPage's
 * AlertSidebar). Confirm posts to the resolve endpoint, which sets the
 * bar's slesh_negozio_id and replays every parked order for that shop_id.
 */
import { useState } from 'react'

import { Modal } from '@/shared/ui/Modal'
import { useBarsForEvent } from '@/features/dashboard/hooks'
import { useResolvePendingShopMapping } from '@/features/alerts/useAlerts'

interface MapShopToBarModalProps {
  isOpen: boolean
  onClose: () => void
  eventId: string
  pendingMappingId: string
  sleshShopId: string
}

export function MapShopToBarModal({
  isOpen, onClose, eventId, pendingMappingId, sleshShopId,
}: MapShopToBarModalProps) {
  const [selectedBarId, setSelectedBarId] = useState('')
  const barsQuery = useBarsForEvent(isOpen ? eventId : null)
  const resolveMutation = useResolvePendingShopMapping()

  function handleClose() {
    setSelectedBarId('')
    resolveMutation.reset()
    onClose()
  }

  function handleConfirm() {
    if (!selectedBarId) return
    resolveMutation.mutate(
      { eventId, pendingId: pendingMappingId, barId: selectedBarId },
      { onSuccess: handleClose },
    )
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={`Map Slesh shop ${sleshShopId} to a bar`}
    >
      <div className="space-y-3">
        <p className="text-sm text-[#4A5568]">
          Every order parked for this shop_id will be replayed into the
          bar you pick — same recipe cascade as a live order.
        </p>

        <select
          className="w-full text-sm border border-[#E2E8F0] rounded-lg px-2 py-1.5 bg-white text-[#1A202C] cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          value={selectedBarId}
          onChange={(e) => setSelectedBarId(e.target.value)}
          disabled={barsQuery.isLoading || resolveMutation.isPending}
        >
          <option value="">
            {barsQuery.isLoading ? 'Loading bars…' : 'Select a bar…'}
          </option>
          {(barsQuery.data ?? []).map((bar) => (
            <option key={bar.id} value={bar.id}>
              {bar.name}
            </option>
          ))}
        </select>

        {resolveMutation.isError && (
          <p className="text-xs text-[#E53E3E]">
            Failed to resolve — please try again.
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={handleClose}
            className="text-xs px-3 py-1.5 rounded-md border border-[#E2E8F0] text-[#4A5568] hover:bg-[#F7FAFC]"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!selectedBarId || resolveMutation.isPending}
            className="text-xs px-3 py-1.5 rounded-md bg-[#1E5A8D] text-white hover:bg-[#174a78] disabled:opacity-50"
          >
            {resolveMutation.isPending ? 'Mapping…' : 'Confirm'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
