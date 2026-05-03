/**
 * Wristband Activity Feed hook.
 *
 * Backend: GET /api/v1/pos/wristband-activity?event_id=...&limit=...
 * (returns WristbandActivityResponse from backend/app/modules/pos/router.py).
 *
 * Polls every 15s while the dashboard is open. Fast enough to feel live,
 * slow enough to not hammer the API. Aligned with the rest of the dashboard.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type WristbandActivityRow = {
  transaction_id: string
  created_at:     string   // ISO-8601, UTC
  bar_id:         string
  bar_name:       string
  product_id:     string
  product_name:   string
  qty:            number
  price_cents:    number | null
}

export type WristbandActivityResponse = {
  rows:  WristbandActivityRow[]
  total: number
}

export const wristbandKeys = {
  all:     ['wristband-activity'] as const,
  byEvent: (eventId: string | null | undefined, limit: number) =>
    [...wristbandKeys.all, eventId ?? 'none', limit] as const,
} as const

const ACTIVITY_REFETCH_MS = 15_000
const DEFAULT_LIMIT       = 50

export function useWristbandActivity(
  eventId: string | null | undefined,
  limit: number = DEFAULT_LIMIT,
) {
  return useQuery<WristbandActivityResponse>({
    queryKey: wristbandKeys.byEvent(eventId, limit),
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('limit', String(limit))
      if (eventId) params.set('event_id', eventId)
      const { data } = await api.get<WristbandActivityResponse>(
        `/pos/wristband-activity?${params.toString()}`,
      )
      return data
    },
    refetchInterval:        ACTIVITY_REFETCH_MS,
    refetchIntervalInBackground: false,
    staleTime:              5_000,
    enabled:                eventId !== undefined,    // run even with null (= brand-wide)
  })
}
