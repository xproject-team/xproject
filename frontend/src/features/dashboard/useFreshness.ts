/**
 * Slesh polling freshness hook.
 *
 * Backend: GET /api/v1/pos/freshness  (returns FreshnessResponse from
 * backend/app/modules/pos/router.py).
 *
 * Polls every 10s while the dashboard is open so Omar can see at a glance
 * whether the polling worker is keeping up with Slesh. Slow refresh
 * (vs the 15s used elsewhere) because the user wants this badge to feel
 * "almost live" — staleness here is the WHOLE POINT of the indicator.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type FreshnessResponse = {
  has_state:     boolean
  last_run_at:   string | null   // ISO-8601, UTC
  last_status:   'ok' | 'error' | 'circuit_open' | null
  last_error:    string | null
  seconds_since: number | null
  is_live:       boolean
  is_stale:      boolean
  brand_id:      string | null
}

export const freshnessKeys = {
  all: ['freshness'] as const,
} as const

const FRESHNESS_REFETCH_MS = 10_000

export function useFreshness() {
  return useQuery<FreshnessResponse>({
    queryKey: freshnessKeys.all,
    queryFn: async () => {
      const { data } = await api.get<FreshnessResponse>('/pos/freshness')
      return data
    },
    refetchInterval:        FRESHNESS_REFETCH_MS,
    refetchIntervalInBackground: false,
    staleTime:              5_000,
  })
}
