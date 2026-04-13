/**
 * useDashboard — TanStack Query hook for fetching live dashboard metrics.
 * Reads the active event ID from the Zustand store.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useDashboard(eventId: string | null) {
  return useQuery({
    queryKey: ['dashboard', eventId],
    queryFn: async () => {
      const { data } = await api.get(`/events/${eventId}/dashboard`)
      return data
    },
    enabled: eventId !== null,
    refetchInterval: 15_000,
  })
}
