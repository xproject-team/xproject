/**
 * Reports TanStack Query hooks.
 *
 * Contract-first: TypeScript interfaces mirror backend Pydantic schemas.py
 * (snake_case throughout). Every hook call translates directly to one REST
 * endpoint from docs/report-module-spec.md §7.
 *
 * Hooks:
 *   usePortfolioKpis      — 4-tile index strip; rare refetch
 *   useReports            — paginated index list; refetch on mutation
 *   useReportsForEvent    — all versions for an event (audit trail)
 *   useReport             — full detail with inline ReportData
 *   useGenerateReport     — on-demand generation (idempotent)
 *   useRegenerateReport   — admin-only, creates v+1
 *
 * PDF download is a direct blob fetch (not a hook) — see downloadReportPdf()
 * at the bottom.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'

import { api } from '@/lib/api'

// ─── Types (match backend schemas.py 1:1) ────────────────────────────────────

export type ReportStatus = 'pending' | 'generating' | 'ready' | 'failed'
export type ReportLanguage = 'it' | 'en'

export type AlertType = 'depletion' | 'anomaly' | 'discrepancy' | 'system'
export type AlertSeverity = 'info' | 'warning' | 'critical' | 'anomaly'
export type AlertAudience = 'owner_only' | 'owner_and_manager'

export interface ReportEventInfo {
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

export interface ReportRevenueKpis {
  total_revenue: string // Decimal comes over the wire as a string
  revenue_per_hour: string
  revenue_per_bar_avg: string
  // Confirmed-order revenue not yet attributable to any bar (unmapped POS
  // shop). Included in total_revenue; "0" on pre-migration reports.
  unmapped_revenue: string
  top_product_name: string | null
  top_product_units: number | null
  peak_hour_start: string | null
  peak_hour_revenue: string | null
}

export interface ReportBarRevenue {
  bar_id: string
  bar_name: string
  revenue: string
  revenue_pct: number
  transactions_count: number
  rank: number
}

export interface ReportStockRow {
  bar_id: string
  bar_name: string
  product_id: string
  product_name: string
  opening_qty: string
  closing_qty: string
  consumed_qty: string
  burn_rate_per_hour: string
  stock_out_occurred: boolean
  stock_out_time: string | null
  consumption_vs_plan_pct: number | null
}

export interface ReportAlertRow {
  alert_id: string
  alert_type: AlertType
  severity: AlertSeverity
  bar_id: string | null
  bar_name: string | null
  title: string
  owner_message: string
  fired_at: string
  acknowledged_at: string | null
  acknowledged_by_name: string | null
  audience: AlertAudience
}

export interface ReportNarrative {
  what_happened: string
  what_worked: string
  what_next: string[]
}

// Section A — Guests. identified_total is a FLOOR on attendance (guests who
// made an identified purchase), never a headcount — see backend
// ReportGuestKpis docstring. available=false is the normal state whenever
// customer_sessions hasn't been populated for this event yet.
export interface ReportGuestKpis {
  available: boolean
  unavailable_reason: string | null
  identified_total: number
  registered_count: number
  guest_count: number
  unknown_count: number
  whale_count: number
  regular_count: number
  light_count: number
  whale_threshold_cents: number
  light_threshold_cents: number
  returning_count: number
  new_count: number
}

export interface ReportForecastHourRow {
  hour_of_event: number
  predicted: number
  actual: number
  lower: number
  upper: number
  within_band: boolean
}

// Section B — Forecast vs. Actual. band_hits/band_hours_total power the
// "actual fell within the predicted range in N of M hours" headline —
// deliberately shown instead of an error percentage.
export interface ReportForecastAccuracy {
  available: boolean
  unavailable_reason: string | null
  predicted_final_total: number | null
  actual_final_total: number | null
  hours: ReportForecastHourRow[]
  band_hits: number | null
  band_hours_total: number | null
}

export interface ReportComparisonMetric {
  label: string
  // 'eur' | 'count' drive value formatting; null on pre-migration reports
  // (renderers fall back to plain numeric formatting).
  unit: 'eur' | 'count' | null
  current_value: number | null
  previous_event_value: number | null
  previous_event_delta_pct: number | null
  season_avg_value: number | null
  season_avg_delta_pct: number | null
}

// Section C — Event-over-Event Comparison. guest_metrics_available_from is
// set (e.g. "August 2026") whenever this event predates guest-comparison
// data — NOT backfilled onto older reports, so say so plainly instead of
// silently omitting rows.
export interface ReportComparison {
  available: boolean
  unavailable_reason: string | null
  previous_event_name: string | null
  previous_event_date: string | null
  season_avg_n_events: number
  metrics: ReportComparisonMetric[]
  guest_metrics_available_from: string | null
  // True when compared reports were measured with the pre-migration
  // revenue method — deltas carry a definitional component; render the
  // footnote.
  mixed_revenue_sources: boolean
}

// Section D — Revenue Decomposition. estimated_attendance is
// expected_guest_count VERBATIM — a planning figure, never a measurement.
// purchase_rate_pct is therefore also an estimate and MUST be labeled as
// such everywhere it's rendered (CAVEAT 2) — never shown as a measured
// conversion rate.
export interface ReportRevenueDecomposition {
  available: boolean
  unavailable_reason: string | null
  estimated_attendance: number | null
  purchasers: number | null
  purchase_rate_pct: number | null
  orders_per_purchaser: number | null
  average_order_value_cents: number | null
  implied_revenue_cents: number | null
  actual_revenue_cents: number | null
}

export interface ReportProductRow {
  product_id: string
  product_name: string
  category: string | null
  units_sold: number
  revenue_cents: number
  category_revenue_share_pct: number | null
}

// Section E — top and lowest-selling products. "lowest_selling", never
// "bottom"/"worst" — present as a question (new item? priced high? quiet
// bar?), never a verdict.
export interface ReportProductPerformance {
  top_products: ReportProductRow[]
  lowest_selling_products: ReportProductRow[]
}

export interface ReportData {
  report_id: string
  version: number
  language: ReportLanguage
  generated_at: string
  // Which method produced the euro figures: 'event_orders' from the Day 14
  // migration onward; null on older frozen snapshots (stock_transactions).
  revenue_source: 'stock_transactions' | 'event_orders' | null
  event: ReportEventInfo
  revenue_kpis: ReportRevenueKpis
  bar_revenues: ReportBarRevenue[]
  stock_rows: ReportStockRow[]
  alerts: ReportAlertRow[]
  narrative: ReportNarrative
  // Optional: absent (null) on reports generated before this feature
  // shipped — every consumer must treat null the same as available=false,
  // never as an error.
  guests: ReportGuestKpis | null
  forecast_accuracy: ReportForecastAccuracy | null
  comparison: ReportComparison | null
  revenue_decomposition: ReportRevenueDecomposition | null
  product_performance: ReportProductPerformance | null
}

export interface ReportSummary {
  id: string
  event_id: string
  event_name: string
  event_started_at: string
  event_ended_at: string
  version: number
  status: ReportStatus
  language: ReportLanguage
  generated_at: string | null
  total_revenue: string | null
  alerts_count: number | null
  top_bar_name: string | null
}

export interface ReportResponse {
  id: string
  event_id: string
  version: number
  superseded_by: string | null
  status: ReportStatus
  language: ReportLanguage
  generated_at: string | null
  data: ReportData | null
}

export interface PortfolioKpis {
  total_events_completed: number
  lifetime_revenue: string
  avg_event_revenue: string
  best_event_name: string | null
  best_event_revenue: string | null
  events_delta_vs_last_quarter: number
  revenue_delta_pct_yoy: number | null
  avg_revenue_delta_vs_last_quarter: string | null
}

export interface GenerateReportRequest {
  event_id: string
  language?: ReportLanguage // defaults to 'it' on the backend
}

export interface RegenerateReportRequest {
  language?: ReportLanguage
}

// ─── Query keys (centralized for easy invalidation) ──────────────────────────

export const reportsKeys = {
  all: ['reports'] as const,
  portfolioKpis: () => [...reportsKeys.all, 'portfolio-kpis'] as const,
  list: (filters?: { status?: ReportStatus; language?: ReportLanguage }) =>
    [...reportsKeys.all, 'list', filters ?? {}] as const,
  forEvent: (eventId: string) =>
    [...reportsKeys.all, 'for-event', eventId] as const,
  detail: (reportId: string, language?: ReportLanguage) =>
    [...reportsKeys.all, 'detail', reportId, language ?? 'default'] as const,
}

// ─── Read hooks ──────────────────────────────────────────────────────────────

export function usePortfolioKpis(
  options?: Omit<UseQueryOptions<PortfolioKpis>, 'queryKey' | 'queryFn'>,
) {
  return useQuery<PortfolioKpis>({
    queryKey: reportsKeys.portfolioKpis(),
    queryFn: async () => {
      const { data } = await api.get<PortfolioKpis>('/reports/portfolio/kpis')
      return data
    },
    staleTime: 60_000, // 1 min — portfolio data doesn't change often
    ...options,
  })
}

export function useReports(filters?: {
  status?: ReportStatus
  language?: ReportLanguage
  event_id?: string
  limit?: number
}) {
  return useQuery<ReportSummary[]>({
    queryKey: reportsKeys.list(filters),
    queryFn: async () => {
      const { data } = await api.get<ReportSummary[]>('/reports', {
        params: filters,
      })
      return data
    },
    staleTime: 30_000,
  })
}

export function useReportsForEvent(eventId: string | null) {
  return useQuery<ReportSummary[]>({
    queryKey: eventId ? reportsKeys.forEvent(eventId) : reportsKeys.forEvent(''),
    queryFn: async () => {
      const { data } = await api.get<ReportSummary[]>(
        `/reports/events/${eventId}`,
      )
      return data
    },
    enabled: eventId !== null,
  })
}

export function useReport(
  reportId: string | null,
  language?: ReportLanguage,
) {
  return useQuery<ReportResponse>({
    queryKey: reportId
      ? reportsKeys.detail(reportId, language)
      : reportsKeys.detail('', language),
    queryFn: async () => {
      const { data } = await api.get<ReportResponse>(`/reports/${reportId}`, {
        params: language ? { lang: language } : undefined,
      })
      return data
    },
    enabled: reportId !== null,
  })
}

// ─── Mutation hooks ──────────────────────────────────────────────────────────

export function useGenerateReport() {
  const qc = useQueryClient()
  return useMutation<ReportResponse, Error, GenerateReportRequest>({
    mutationFn: async (body) => {
      const { data } = await api.post<ReportResponse>(
        '/reports/generate',
        body,
      )
      return data
    },
    onSuccess: () => {
      // Invalidate everything reports-related — list + portfolio both refresh
      qc.invalidateQueries({ queryKey: reportsKeys.all })
    },
  })
}

export function useRegenerateReport(reportId: string) {
  const qc = useQueryClient()
  return useMutation<ReportResponse, Error, RegenerateReportRequest>({
    mutationFn: async (body) => {
      const { data } = await api.post<ReportResponse>(
        `/reports/${reportId}/regenerate`,
        body,
      )
      return data
    },
    onSuccess: (newReport) => {
      // The old report now has superseded_by set — refresh its detail too
      qc.invalidateQueries({ queryKey: reportsKeys.all })
      qc.invalidateQueries({ queryKey: reportsKeys.detail(newReport.id) })
      qc.invalidateQueries({ queryKey: reportsKeys.detail(reportId) })
    },
  })
}

// ─── Helpers (not hooks) ─────────────────────────────────────────────────────

/**
 * Trigger a PDF download for a given report. Not a hook — fires when called.
 * Returns a blob the caller can save via <a download> or similar.
 *
 * The backend renders pdf_bytes synchronously as part of report generation
 * (ReportLab + Matplotlib, see backend/app/modules/reports/pdf.py) — any
 * 'ready' report already has a PDF. A 404 here means the report itself
 * doesn't exist or isn't ready yet, not a missing feature.
 */
export async function downloadReportPdf(reportId: string): Promise<Blob> {
  const { data } = await api.get<Blob>(`/reports/${reportId}/pdf`, {
    responseType: 'blob',
  })
  return data
}
