/**
 * useReports — TanStack Query hook for fetching and triggering report generation.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useReport(eventId: string | null) {
  return useQuery({
    queryKey: ['report', eventId],
    queryFn: async () => {
      const { data } = await api.get(`/reports`, { params: { event_id: eventId } })
      return data
    },
    enabled: eventId !== null,
  })
}

export function useGenerateReport(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/reports/generate`, { event_id: eventId })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['report', eventId] }),
  })
}
