/**
 * useEvents — TanStack Query hook for listing and managing events.
 * All API calls go through lib/api.ts; never call axios directly in components.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { EventResponse } from '@/lib/types'

export function useEvents() {
  const query = useQuery<EventResponse[]>({
    queryKey: ['events'],
    queryFn: async () => {
      const { data } = await api.get('/events')
      return data
    },
  })

  return {
    events: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  }
}
