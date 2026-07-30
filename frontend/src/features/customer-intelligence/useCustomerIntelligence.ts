/**
 * useCustomerIntelligence — Day 4 Customer Intelligence panel.
 *
 * Backend: GET /api/v1/events/{eventId}/customer-intelligence. Response
 * shape matches CustomerIntelligenceResponse from
 * backend/app/modules/customer_intelligence/schemas.py exactly (same
 * "keep backend field names, don't relabel" convention as
 * useRevenueForecast).
 *
 * Status-dependent behavior mirrors useRevenueForecast exactly:
 *   - 'live'      -> polls every 30s (as_of_time omitted; backend
 *                    defaults to now and serves from its own ~30s
 *                    cache, so this poll cadence matches what's
 *                    actually fresh server-side).
 *   - 'completed' -> fetches once at endedAt (a post-mortem read, same
 *                    "we predicted X, actual was Y" value the revenue
 *                    panel already gets).
 *   - anything else -> disabled.
 *
 * Never throws into the render tree: `data` maps to `null` on any
 * not-yet-loaded/errored state, so CustomerIntelligencePanel never has
 * to distinguish undefined vs null vs error.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export interface ConfidenceInterval {
  lower:          number
  upper:          number
  half_width_pct: number
  calibrated:     boolean
}

export interface CategoryForecast {
  category:        string
  predicted_count: number
  low_confidence:  boolean
}

export interface NextHourForecast {
  predicted_total:      number
  confidence_interval:  ConfidenceInterval
  category_breakdown:   CategoryForecast[]
}

export interface DemandForecast {
  available:              boolean
  unavailable_reason?:    string | null
  predicted_final_total?: number | null
  confidence?:            number | null
  confidence_interval?:   ConfidenceInterval | null
  next_hour?:             NextHourForecast | null
  hot_night_applied:      boolean
}

export interface HourlyPredictedVsActual {
  hour_of_event: number
  predicted:     number
  actual:        number
}

export interface GuestCounts {
  live_identified_count: number
  projected_final:       number | null
  registered_count:      number
  guest_count:            number
  unknown_count:          number
}

export interface SpendSegments {
  whale_count:            number
  regular_count:          number
  light_count:            number
  whale_threshold_cents:  number
  light_threshold_cents:  number
}

export interface ReturningGuests {
  returning_count:   number
  new_count:         number
  identified_total:  number
}

export interface CustomerIntelligenceResponse {
  event_id:                string
  as_of_time:              string
  hour_offset_from_start:  number | null
  guests:                  GuestCounts
  spend_segments:          SpendSegments
  returning_guests:        ReturningGuests
  demand_forecast:         DemandForecast
  predicted_vs_actual:     HourlyPredictedVsActual[]
  hot_night_override:      boolean
}

export const customerIntelKeys = {
  all:     ['customer-intelligence'] as const,
  byEvent: (eventId: string | null | undefined, asOfTime: string | undefined) =>
    ['customer-intelligence', eventId ?? 'none', asOfTime ?? 'now'] as const,
} as const

const REFETCH_MS = 30_000

export function useCustomerIntelligence(
  eventId: string | null | undefined,
  eventStatus: string | null | undefined,
  endedAt?: string | null,
) {
  const isLive = eventStatus === 'live'
  const isCompleted = eventStatus === 'completed'
  const asOfTime = isCompleted ? (endedAt ?? undefined) : undefined

  const query = useQuery<CustomerIntelligenceResponse>({
    queryKey: customerIntelKeys.byEvent(eventId, asOfTime),
    queryFn: async () => {
      const params = asOfTime ? `?as_of_time=${encodeURIComponent(asOfTime)}` : ''
      const { data } = await api.get<CustomerIntelligenceResponse>(
        `/events/${eventId}/customer-intelligence${params}`,
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
    data:    query.data ?? null,
    loading: query.isLoading,
    error:   (query.error as Error | null) ?? null,
  }
}

/** Manual "hot night" toggle (Day 4). Off by default, never automatic
 * — see predictor.py's apply_hot_night_boost. Invalidates the
 * customer-intelligence cache on success so the panel reflects the new
 * state (and the boosted/unboosted forecast) immediately. */
export function useSetHotNightOverride(eventId: string | null | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const { data } = await api.post<{ event_id: string; hot_night_override: boolean }>(
        `/events/${eventId}/hot-night-override`,
        { enabled },
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: customerIntelKeys.all })
    },
  })
}
