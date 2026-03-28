/**
 * usePredictions — TanStack Query hook for fetching ML demand predictions.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function usePredictions(eventId: number | null) {
  return useQuery({
    queryKey: ['predictions', eventId],
    queryFn: async () => {
      const { data } = await api.get('/predictions', { params: { event_id: eventId } })
      return data
    },
    enabled: eventId !== null,
  })
}
