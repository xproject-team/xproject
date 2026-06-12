import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type {
  ActivityFeedRow,
  BarAllocationSummary,
  DispatchCreate,
  DispatchResponse,
  EventStockItem,
  EventStockItemCreate,
  StorageSummary,
  SupplierProduct,
} from './types'

export const eventStorageKeys = {
  all: ['event-storage'] as const,
  supplierProducts: () => ['event-storage', 'supplier-products'] as const,
  itemsForEvent: (eventId: string) =>
    ['event-storage', 'items', eventId] as const,
  summaryForEvent: (eventId: string) =>
    ['event-storage', 'summary', eventId] as const,
  activityForEvent: (eventId: string, limit: number) =>
    ['event-storage', 'activity', eventId, limit] as const,
  byBarForEvent: (eventId: string) =>
    ['event-storage', 'by-bar', eventId] as const,
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

// ─── Warehouse / Inventory hooks ──────────────────────────────────────

export function useStorageSummary(eventId: string | undefined) {
  return useQuery({
    queryKey: eventId
      ? eventStorageKeys.summaryForEvent(eventId)
      : ['event-storage', 'summary', 'no-event'],
    queryFn: async () => {
      const { data } = await api.get<StorageSummary>(
        `/event-storage/summary?event_id=${eventId}`,
      )
      return data
    },
    enabled: Boolean(eventId),
    staleTime: 15_000,
  })
}

export function useActivityFeed(
  eventId: string | undefined,
  limit: number = 50,
) {
  return useQuery({
    queryKey: eventId
      ? eventStorageKeys.activityForEvent(eventId, limit)
      : ['event-storage', 'activity', 'no-event'],
    queryFn: async () => {
      const { data } = await api.get<ActivityFeedRow[]>(
        `/event-storage/activity?event_id=${eventId}&limit=${limit}`,
      )
      return data
    },
    enabled: Boolean(eventId),
    staleTime: 10_000,
  })
}

export function useBarAllocations(eventId: string | undefined) {
  return useQuery({
    queryKey: eventId
      ? eventStorageKeys.byBarForEvent(eventId)
      : ['event-storage', 'by-bar', 'no-event'],
    queryFn: async () => {
      const { data } = await api.get<BarAllocationSummary[]>(
        `/event-storage/by-bar?event_id=${eventId}`,
      )
      return data
    },
    enabled: Boolean(eventId),
    staleTime: 15_000,
  })
}

export function useCreateDispatch(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: DispatchCreate) => {
      const { data } = await api.post<DispatchResponse>(
        `/event-storage/allocations?event_id=${eventId}`,
        payload,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: eventStorageKeys.summaryForEvent(eventId),
      })
      qc.invalidateQueries({
        queryKey: eventStorageKeys.byBarForEvent(eventId),
      })
      qc.invalidateQueries({
        queryKey: ['event-storage', 'activity', eventId],
      })
    },
  })
}

export function useBulkCreateDispatches(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (items: DispatchCreate[]) => {
      const { data } = await api.post<DispatchResponse[]>(
        `/event-storage/allocations/bulk?event_id=${eventId}`,
        { items },
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: eventStorageKeys.summaryForEvent(eventId),
      })
      qc.invalidateQueries({
        queryKey: eventStorageKeys.byBarForEvent(eventId),
      })
      qc.invalidateQueries({
        queryKey: ['event-storage', 'activity', eventId],
      })
    },
  })
}
