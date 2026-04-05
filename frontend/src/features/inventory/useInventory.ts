/**
 * useInventory — TanStack Query hook for fetching inventory items for a bar.
 * Components never call axios directly; always use this hook.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { InventoryItemResponse } from '@/lib/types'

export function useInventory(eventId: number | null, barId?: number) {
  return useQuery<InventoryItemResponse[]>({
    queryKey: ['inventory', eventId, barId],
    queryFn: async () => {
      const params = barId !== undefined ? { bar_id: barId } : {}
      const { data } = await api.get(`/inventory`, { params: { event_id: eventId, ...params } })
      return data
    },
    enabled: eventId !== null,
  })
}
