/**
 * useRevenueForecast — the "ML Predicted" revenue nowcast (Phase E,
 * extended to COMPLETED events for post-mortem review — see below).
 *
 * Backend: GET /api/v1/events/{eventId}/revenue-forecast (Phase D —
 * see backend/app/modules/predictions/nowcast/). Response shape
 * matches RevenueForecastResponse from
 * backend/app/modules/predictions/nowcast/schemas.py exactly.
 *
 * Status-dependent behavior:
 *   - 'live'      -> polls every 30s (as_of_time omitted; backend
 *                    defaults to now). 30s matches the dashboard's
 *                    existing polling proportions (wristband activity
 *                    feed is 15s and is meant to feel second-by-second
 *                    live; this is a slower-moving KPI — the
 *                    underlying shape_curve only changes at hour
 *                    granularity — so 30s is deliberately more
 *                    relaxed, not a corner cut).
 *   - 'completed' -> fetches ONCE with as_of_time=endedAt (a completed
 *                    event's revenue is final — nothing to poll for).
 *                    If endedAt is missing, falls back to omitting
 *                    as_of_time entirely (backend defaults to now,
 *                    which for an event that's truly over yields the
 *                    same full tally as any later timestamp would —
 *                    no more transactions are coming in for it).
 *   - anything else (draft, etc.) -> disabled entirely. Nothing to
 *                    predict yet.
 *
 * Frontend status values are lowercase ('draft'|'live'|'completed',
 * see src/lib/mockData.ts's Event type) — NOT the backend's uppercase
 * EventStatus enum values.
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
  // Phase F metadata — additive, backend-only until a future UI surfaces it.
  training_events_count:       number
  training_last_updated_at:    string
  year_weighted_prior_used:    boolean
}

export const revenueForecastKeys = {
  byEvent: (eventId: string | null | undefined, asOfTime: string | undefined) =>
    ['revenue-forecast', eventId ?? 'none', asOfTime ?? 'now'] as const,
} as const

const REFETCH_MS = 30_000

export function useRevenueForecast(
  eventId: string | null | undefined,
  eventStatus: string | null | undefined,
  endedAt?: string | null,
) {
  const isLive = eventStatus === 'live'
  const isCompleted = eventStatus === 'completed'
  const asOfTime = isCompleted ? (endedAt ?? undefined) : undefined

  const query = useQuery<RevenueForecastResponse>({
    queryKey: revenueForecastKeys.byEvent(eventId, asOfTime),
    queryFn: async () => {
      const params = asOfTime ? `?as_of_time=${encodeURIComponent(asOfTime)}` : ''
      const { data } = await api.get<RevenueForecastResponse>(
        `/events/${eventId}/revenue-forecast${params}`,
      )
      return data
    },
    refetchInterval:             isLive ? REFETCH_MS : false,
    refetchIntervalInBackground: false,
    staleTime:                   isCompleted ? Infinity : 10_000,
    enabled:                     Boolean(eventId) && (isLive || isCompleted),
    retry:                       1,
  })

  return {
    forecast: query.data ?? null,
    loading:  query.isLoading,
    error:    (query.error as Error | null) ?? null,
  }
}
