/**
 * useAlerts — TanStack Query hook for fetching active alerts for an event.
 * Polls every 10s to surface new alerts without a WebSocket connection.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useAlerts(eventId: number | null) {
  return useQuery({
    queryKey: ['alerts', eventId],
    queryFn: async () => {
      const { data } = await api.get('/alerts', { params: { event_id: eventId } })
      return data
    },
    enabled: eventId !== null,
    refetchInterval: 10_000,
  })
}
