/**
 * useRevenueForecast — the "ML Predicted" revenue nowcast (Phase E).
 *
 * Backend: GET /api/v1/events/{eventId}/revenue-forecast (Phase D —
 * see backend/app/modules/predictions/nowcast/). Response shape
 * matches RevenueForecastResponse from
 * backend/app/modules/predictions/nowcast/schemas.py exactly.
 *
 * Polls every 30s. Callers should pass eventId only while the event is
 * LIVE (e.g. `useRevenueForecast(isLive ? eventId : null)`) — passing
 * null disables the query, which also stops the poll. 30s matches the
 * dashboard's existing polling proportions (wristband activity feed is
 * 15s and is meant to feel second-by-second live; this is a slower-
 * moving KPI — the underlying shape_curve only changes at hour
 * granularity — so 30s is deliberately more relaxed, not a corner cut).
 *
 * "Falls back to null on any error, no throw": React Query already
 * doesn't throw into the render tree on query failure (no throwOnError/
 * suspense configured — see src/app/providers.tsx). This hook maps
 * `data` to `forecast: null` on any not-yet-loaded/errored state so
 * RevenueForecastPanel never has to distinguish undefined vs null.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type NowcastConfidenceTier = 'early' | 'directional' | 'trustworthy'

export interface PredictedCurvePoint {
  hour_offset:            number
  cumulative_revenue_eur: number
}

export interface HistoricalRangeEur {
  min: number
  max: number
}

export interface RevenueForecastResponse {
  event_id:                    string
  as_of_time:                  string
  hour_offset_from_start:      number
  current_revenue_eur:         number
  predicted_final_revenue_eur: number
  predicted_curve:             PredictedCurvePoint[]
  confidence:                  number
  vs_historical_avg_eur:       number
  historical_range_eur:        HistoricalRangeEur
  historical_n:                number
  confidence_tier:             NowcastConfidenceTier
}

export const revenueForecastKeys = {
  byEvent: (eventId: string | null | undefined) =>
    ['revenue-forecast', eventId ?? 'none'] as const,
} as const

const REFETCH_MS = 30_000

export function useRevenueForecast(eventId: string | null | undefined) {
  const query = useQuery<RevenueForecastResponse>({
    queryKey: revenueForecastKeys.byEvent(eventId),
    queryFn: async () => {
      const { data } = await api.get<RevenueForecastResponse>(
        `/events/${eventId}/revenue-forecast`,
      )
      return data
    },
    refetchInterval:             REFETCH_MS,
    refetchIntervalInBackground: false,
    staleTime:                   10_000,
    enabled:                     Boolean(eventId),
    retry:                       1,
  })

  return {
    forecast: query.data ?? null,
    loading:  query.isLoading,
    error:    (query.error as Error | null) ?? null,
  }
}
