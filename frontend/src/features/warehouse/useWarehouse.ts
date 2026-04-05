/**
 * useWarehouse — TanStack Query + mutation hooks for scan submission and history.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useScanHistory(eventId: number | null) {
  return useQuery({
    queryKey: ['scan-history', eventId],
    queryFn: async () => {
      const { data } = await api.get('/warehouse/scans', { params: { event_id: eventId } })
      return data
    },
    enabled: eventId !== null,
  })
}

export function useSubmitScan(eventId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { barcode: string; action: string; quantity: number }) => {
      const { data } = await api.post(`/warehouse/scans`, { ...payload, event_id: eventId })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scan-history', eventId] }),
  })
}
