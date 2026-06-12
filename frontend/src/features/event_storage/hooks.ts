import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  EventStockItem,
  EventStockItemCreate,
  SupplierProduct,
} from './types'

export const eventStorageKeys = {
  all: ['event-storage'] as const,
  supplierProducts: () => ['event-storage', 'supplier-products'] as const,
  itemsForEvent: (eventId: string) =>
    ['event-storage', 'items', eventId] as const,
} as const

export function useSupplierProducts() {
  return useQuery({
    queryKey: eventStorageKeys.supplierProducts(),
    queryFn: async () => {
      const { data } = await api.get<SupplierProduct[]>(
        `/event-storage/supplier-products`,
      )
      return data
    },
    staleTime: 60_000,
  })
}

export function useEventStockItems(eventId: string | undefined) {
  return useQuery({
    queryKey: eventId
      ? eventStorageKeys.itemsForEvent(eventId)
      : ['event-storage', 'items', 'no-event'],
    queryFn: async () => {
      const { data } = await api.get<EventStockItem[]>(
        `/event-storage/items?event_id=${eventId}`,
      )
      return data
    },
    enabled: Boolean(eventId),
  })
}

export function useBulkUpsertEventStockItems(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (items: EventStockItemCreate[]) => {
      const { data } = await api.post<EventStockItem[]>(
        `/event-storage/items/bulk?event_id=${eventId}`,
        { items },
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: eventStorageKeys.itemsForEvent(eventId) })
    },
  })
}

export function useDeleteEventStockItem(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (itemId: string) => {
      await api.delete(`/event-storage/items/${itemId}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: eventStorageKeys.itemsForEvent(eventId) })
    },
  })
}
