/**
 * Predictions TanStack Query hooks.
 *
 * Contract-first: TypeScript interfaces mirror backend Pydantic schemas.py
 * (snake_case throughout). Every hook call translates directly to one REST
 * endpoint from docs/predictions-module-spec.md §7.
 *
 * Hooks:
 *   usePredictionForEvent     — latest prediction for an event, or null
 *   usePredictionHistory      — all versions including superseded
 *   usePrediction             — detail view with inline PredictionData
 *   useGeneratePrediction     — on-demand generation (idempotent)
 *   useRegeneratePrediction   — admin-only, creates v+1
 *
 * PredictionInsufficientData is NOT an error — the `status` field on the
 * response is 'insufficient_data' and the `insufficient_data_message` field
 * carries the user-friendly message. Frontend renders the calm empty state.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'

import { api } from '@/lib/api'

// ─── Types (match backend schemas.py 1:1) ────────────────────────────────────

export type PredictionStatus =
  | 'pending'
  | 'generating'
  | 'ready'
  | 'failed'
  | 'insufficient_data'

export type PredictorType = 'heuristic' | 'ml'

export type ConfidenceTier = 'low' | 'medium' | 'high'

export type ProductCategory =
  | 'beer'
  | 'spirits'
  | 'wine'
  | 'mixers'
  | 'cocktails'

export type DemandTrend = 'up' | 'stable' | 'down'

export interface PredictionRange {
  low: string // Decimal as string over the wire
  mid: string
  high: string
  confidence_pct: number
}

export interface PredictionBarRevenue {
  bar_id: string
  bar_name: string
  revenue: PredictionRange
}

export interface PredictionBarStaff {
  bar_id: string
  bar_name: string
  bartenders: PredictionRange
}

export interface PredictionRevenue {
  total: PredictionRange
  per_bar: PredictionBarRevenue[]
  vs_last_event_pct: number | null
}

export interface PredictionCategoryDemand {
  category: ProductCategory
  units: PredictionRange
  trend: DemandTrend
}

export interface PredictionPeakHour {
  window_start: string
  window_end: string
  predicted_revenue_share_pct: number
}

export interface PredictionStaff {
  total_bartenders: PredictionRange
  per_bar: PredictionBarStaff[]
}

export interface PredictionRiskFlag {
  product_id: string
  product_name: string
  bar_id: string
  bar_name: string
  stockout_probability: number
  predicted_stockout_time: string | null
}

export interface ReportEventInfo {
  // Reused from reports — fields identical
  event_id: string
  event_name: string
  venue_name: string
  started_at: string
  ended_at: string
  duration_hours: number
  bars_count: number
  guests_served: number | null
  expected_guest_count: number | null
}

export interface PredictionData {
  prediction_id: string
  version: number
  generated_at: string
  based_on_event_count: number
  confidence_tier: ConfidenceTier
  event: ReportEventInfo
  revenue: PredictionRevenue
  category_demand: PredictionCategoryDemand[]
  peak_hour: PredictionPeakHour | null
  staff: PredictionStaff
  risk_flags: PredictionRiskFlag[]
}

export interface PredictionSummary {
  id: string
  event_id: string
  event_name: string
  version: number
  status: PredictionStatus
  predictor_type: PredictorType
  confidence_tier: ConfidenceTier
  based_on_event_count: number
  generated_at: string | null
}

export interface PredictionResponse {
  id: string
  event_id: string
  version: number
  superseded_by: string | null
  status: PredictionStatus
  predictor_type: PredictorType
  confidence_tier: ConfidenceTier
  based_on_event_count: number
  generated_at: string | null
  data: PredictionData | null
  insufficient_data_message: string | null
}

export interface GeneratePredictionRequest {
  event_id: string
}

// ─── Query keys (centralized for easy invalidation) ──────────────────────────

export const predictionsKeys = {
  all: ['predictions'] as const,
  forEvent: (eventId: string) =>
    [...predictionsKeys.all, 'for-event', eventId] as const,
  history: (eventId: string) =>
    [...predictionsKeys.all, 'history', eventId] as const,
  detail: (predictionId: string) =>
    [...predictionsKeys.all, 'detail', predictionId] as const,
}

// ─── Read hooks ──────────────────────────────────────────────────────────────

/**
 * Latest prediction for an event, or null if never generated.
 *
 * Returns null (not an error) when no prediction has been generated yet.
 * The frontend uses this distinction to show:
 *   - null            → 'Generate Predictions' CTA
 *   - status=insufficient_data → calm empty state with user_message
 *   - status=ready    → full prediction UI
 *   - status=failed   → red banner with failure_reason
 */
export function usePredictionForEvent(
  eventId: string | null,
  options?: Omit<
    UseQueryOptions<PredictionResponse | null>,
    'queryKey' | 'queryFn'
  >,
) {
  return useQuery<PredictionResponse | null>({
    queryKey: eventId
      ? predictionsKeys.forEvent(eventId)
      : predictionsKeys.forEvent(''),
    queryFn: async () => {
      const { data } = await api.get<PredictionResponse | null>(
        `/predictions/events/${eventId}`,
      )
      return data
    },
    enabled: eventId !== null,
    staleTime: 30_000,
    ...options,
  })
}

export function usePredictionHistory(eventId: string | null) {
  return useQuery<PredictionSummary[]>({
    queryKey: eventId
      ? predictionsKeys.history(eventId)
      : predictionsKeys.history(''),
    queryFn: async () => {
      const { data } = await api.get<PredictionSummary[]>(
        `/predictions/events/${eventId}/history`,
      )
      return data
    },
    enabled: eventId !== null,
  })
}

export function usePrediction(predictionId: string | null) {
  return useQuery<PredictionResponse>({
    queryKey: predictionId
      ? predictionsKeys.detail(predictionId)
      : predictionsKeys.detail(''),
    queryFn: async () => {
      const { data } = await api.get<PredictionResponse>(
        `/predictions/${predictionId}`,
      )
      return data
    },
    enabled: predictionId !== null,
  })
}

// ─── Mutation hooks ──────────────────────────────────────────────────────────

export function useGeneratePrediction() {
  const qc = useQueryClient()
  return useMutation<PredictionResponse, Error, GeneratePredictionRequest>({
    mutationFn: async (body) => {
      const { data } = await api.post<PredictionResponse>(
        '/predictions/generate',
        body,
      )
      return data
    },
    onSuccess: (newPrediction) => {
      // Invalidate everything prediction-related for this event
      qc.invalidateQueries({ queryKey: predictionsKeys.all })
      qc.invalidateQueries({
        queryKey: predictionsKeys.forEvent(newPrediction.event_id),
      })
      qc.invalidateQueries({
        queryKey: predictionsKeys.history(newPrediction.event_id),
      })
    },
  })
}

export function useRegeneratePrediction(predictionId: string) {
  const qc = useQueryClient()
  return useMutation<PredictionResponse, Error, Record<string, never>>({
    mutationFn: async () => {
      const { data } = await api.post<PredictionResponse>(
        `/predictions/${predictionId}/regenerate`,
        {},
      )
      return data
    },
    onSuccess: (newPrediction) => {
      qc.invalidateQueries({ queryKey: predictionsKeys.all })
      qc.invalidateQueries({
        queryKey: predictionsKeys.forEvent(newPrediction.event_id),
      })
      qc.invalidateQueries({
        queryKey: predictionsKeys.detail(predictionId),
      })
    },
  })
}
