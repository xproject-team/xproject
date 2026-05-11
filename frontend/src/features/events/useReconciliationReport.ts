/**
 * TanStack Query hook for the reconciliation-report endpoint
 * (Phase 6.11 backend, GET /events/{event_id}/reconciliation-report).
 *
 * Owner-only on the server — but this hook makes no role assumption.
 * Callers should gate the entry-point UI (button, route) with
 * usePermissions().canGenerateReport. If the server returns 403 anyway,
 * the error propagates through TanStack as a normal query error and
 * the page renders an error state.
 *
 * Decimal-as-string contract:
 *   The backend serializes all quantities (arrived_qty, consumed_qty,
 *   dispatched_qty, etc.) as STRINGS to preserve precision. The frontend
 *   keeps them as strings for display — never parseFloat for arithmetic.
 *   If a future feature needs arithmetic, do it with the Decimal.js
 *   library or by sending the math to the backend, not by parsing.
 *
 * Hierarchical query keys: reconciliationKeys.report(eventId).
 * Cache lifetime defaults to TanStack's standard (30s stale time via
 * queryClient default config). The report is naturally fresh because
 * the underlying scans don't move during a post-event review; during
 * a live event the operator can pull-to-refresh by re-entering the page.
 */
import { useQuery } from '@tanstack/react-query'
import { AxiosError } from 'axios'

import { api } from '@/lib/api'

// ─── Query key factory ──────────────────────────────────────────────────────

export const reconciliationKeys = {
  all:    ['reconciliation'] as const,
  report: (eventId: string) =>
    [...reconciliationKeys.all, eventId, 'report'] as const,
} as const

// ─── Response types — mirror backend Pydantic schemas 1:1 ───────────────────

/** Flag values match backend's DeliveryGapFlag Literal exactly. */
export type DeliveryGapFlag =
  | 'DELIVERY_GAP_MINOR'
  | 'DELIVERY_GAP_MODERATE'
  | 'DELIVERY_GAP_MAJOR'

/**
 * One row of the reconciliation grid: a (bar, product) pair with at
 * least one DISPATCH or CONSUMED scan in the event window.
 *
 * All quantities are STRINGS (Decimal-as-string contract).
 */
export interface ReconciliationRow {
  bar_id:        string
  bar_name:      string
  product_id:    string
  product_name:  string
  arrived_qty:   string   // SUM of DISPATCH scans
  consumed_qty:  string   // SUM of CONSUMED scans
  net_qty:       string   // arrived - consumed
  flags:         string[] // empty for MVP; future: row-level over-pour signals
}

/**
 * One per-product event-level gap: warehouse_allocations.dispatched_qty
 * vs the sum of DISPATCH scans across all bars.
 *
 * Includes the catastrophic "dispatched > 0 but zero arrived" pattern
 * as DELIVERY_GAP_MAJOR — the worst signal Omar pays for.
 */
export interface EventProductGap {
  product_id:              string
  product_name:            string
  dispatched_qty:          string
  total_arrived_at_event:  string
  delivery_gap:            string
  gap_pct:                 number | null
  flag:                    DeliveryGapFlag | null
}

/** Aggregate counters for the top-of-page summary cards. */
export interface ReconciliationTotals {
  active_rows:               number
  total_arrived:             string
  total_consumed:            string
  event_delivery_gap_count:  number
  /** True until Slesh POS sandbox is wired. */
  missing_pos_data:          boolean
}

export interface ReconciliationSummary {
  event_level_gaps:  EventProductGap[]
  totals:            ReconciliationTotals
}

/** Top-level response envelope. */
export interface ReconciliationReport {
  event_id:           string
  event_name:         string
  /** Mirrors event_status enum: draft | active | live | completed | cancelled */
  event_status:       string
  event_started_at:   string | null   // ISO 8601, null if event never went live
  event_ended_at:     string | null   // ISO 8601, null if still LIVE
  generated_at:       string          // ISO 8601 — server's snapshot timestamp
  rows:               ReconciliationRow[]
  summary:            ReconciliationSummary
}

// ─── The hook ───────────────────────────────────────────────────────────────

/**
 * Fetch the reconciliation report for one event.
 *
 * Returns the standard TanStack Query result. `data` is the typed
 * ReconciliationReport when status === 'success'; otherwise undefined.
 *
 * Disabled when eventId is null/undefined — useful for the page that
 * reads it from URL params and wants to render a guard state before
 * the query fires.
 */
export function useReconciliationReport(eventId: string | null | undefined) {
  return useQuery<ReconciliationReport, AxiosError>({
    queryKey: eventId
      ? reconciliationKeys.report(eventId)
      : reconciliationKeys.all,
    queryFn: async (): Promise<ReconciliationReport> => {
      const res = await api.get<ReconciliationReport>(
        `/events/${eventId}/reconciliation-report`,
      )
      return res.data
    },
    enabled: Boolean(eventId),
  })
}
