/**
 * Slesh polling freshness hook.
 *
 * Day 4 (Jul-19 sprint) rewire: was GET /api/v1/pos/freshness (brand-wide,
 * tenant-scoped only). Now GET /api/v1/events/{event_id}/polling-health —
 * see backend/app/modules/events/router.py + polling_health_service.py.
 * Same underlying slesh_poll_state row under the hood (still resolved by
 * tenant, since that table has no event_id column — see
 * polling_health_service.py's docstring), but the endpoint now also adds
 * consecutive_failures to the health verdict and 404s instead of
 * returning has_state=false when no poller has ever run for this tenant.
 *
 * Polls every 15s (was 10s) to match the interval locked for this rewire.
 */
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

import { api } from '@/lib/api'

export type FreshnessResponse = {
  last_run_at:             string | null   // ISO-8601, UTC
  seconds_since_last_run:  number | null
  last_status:             string | null   // ok | error | circuit_open
  last_error:              string | null
  consecutive_failures:    number
  is_healthy:              boolean
}

export const freshnessKeys = {
  all:  ['freshness'] as const,
  byEvent: (eventId: string) => [...freshnessKeys.all, eventId] as const,
} as const

const FRESHNESS_REFETCH_MS = 15_000

export function useFreshness(eventId: string | null | undefined) {
  return useQuery<FreshnessResponse | null>({
    queryKey: freshnessKeys.byEvent(eventId ?? 'none'),
    queryFn: async () => {
      try {
        const { data } = await api.get<FreshnessResponse>(
          `/events/${eventId}/polling-health`,
        )
        return data
      } catch (err) {
        // 404 = no slesh_poll_state row yet for this tenant (poller has
        // never run) — a normal "nothing to show" case, not an error.
        if (axios.isAxiosError(err) && err.response?.status === 404) return null
        throw err
      }
    },
    enabled:                     Boolean(eventId),
    refetchInterval:              FRESHNESS_REFETCH_MS,
    refetchIntervalInBackground: false,
    staleTime:                    5_000,
  })
}
