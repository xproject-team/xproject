/**
 * TanStack Query hooks for the Dashboard data layer.
 *
 * Read-only hooks that fetch from the endpoints built in backend Steps 2-6:
 *   useLiveEvent            → /api/v1/events?status=live  (pick active event)
 *   useBarsForEvent         → /api/v1/bars?event_id=...
 *   useBarStockForEvent     → /api/v1/bar-stock/by-event/{event_id}
 *   useReconciliation       → /api/v1/stock-transactions/reconciliation/by-event/{event_id}
 *   useTransactionsForEvent → /api/v1/stock-transactions/by-event/{event_id}
 *   useAllProducts          → /api/v1/products (for tier_rank + name lookup)
 *
 * Design notes (match the Events hooks pattern in features/events/hooks.ts):
 * - Hierarchical query keys under `dashboardKeys` for surgical invalidation
 * - `enabled` gates so child queries don't fire before the parent resolves
 * - `refetchInterval: 15s` on the live-data queries so the dashboard feels
 *   live without WebSocket wiring (that comes in Step 7b)
 * - All hooks return raw backend shapes — transformation to BarKpi happens
 *   in features/dashboard/selectors.ts, not here
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  BarRow,
  BarStockRow,
  Event,
  ProductRow,
  ReconciliationReport,
  StockTransactionRow,
} from '@/lib/mockData'

// ─── Query keys (hierarchical — invalidate a branch, not individual queries) ──

export const dashboardKeys = {
  all:            ['dashboard'] as const,
  liveEvent:      () => [...dashboardKeys.all, 'liveEvent'] as const,
  allProducts:    () => [...dashboardKeys.all, 'products'] as const,
  bars:           (eventId: string) =>
    [...dashboardKeys.all, 'bars', eventId] as const,
  barStock:       (eventId: string) =>
    [...dashboardKeys.all, 'barStock', eventId] as const,
  reconciliation: (eventId: string) =>
    [...dashboardKeys.all, 'reconciliation', eventId] as const,
  transactions:   (eventId: string) =>
    [...dashboardKeys.all, 'transactions', eventId] as const,
  burnRate:       (eventId: string) =>
    [...dashboardKeys.all, 'burnRate', eventId] as const,
  barCategoryTotals: (eventId: string) =>
    [...dashboardKeys.all, 'barCategoryTotals', eventId] as const,
  kpiSummary: (eventId: string) =>
    [...dashboardKeys.all, 'kpiSummary', eventId] as const,
  menuPerformance: (eventId: string) =>
    [...dashboardKeys.all, 'menuPerformance', eventId] as const,
} as const

// ─── Poll interval for "live" data during an event ────────────────────────────
// 15s = fast enough to feel responsive, slow enough to not hammer the API.
// Once Step 7b adds WebSocket invalidation this becomes a fallback.
const LIVE_REFETCH_MS = 15_000

// ─── Live event auto-select ──────────────────────────────────────────────────
// Returns the first LIVE event for the tenant, or null if none.
// We ask the backend to filter; the events endpoint currently returns ALL
// events and we filter client-side. If that ever gets slow we can add
// ?status=live to the backend query.

export function useLiveEvent() {
  return useQuery<Event | null>({
    queryKey: dashboardKeys.liveEvent(),
    queryFn: async () => {
      const { data } = await api.get<Event[]>('/events')
      const live = data.find((e) => e.status === 'live')
      return live ?? null
    },
    // Poll every 30s so a Go-Live transition is picked up automatically
    refetchInterval: 30_000,
  })
}

// ─── Bars for an event ────────────────────────────────────────────────────────

export function useBarsForEvent(eventId: string | null | undefined) {
  return useQuery<BarRow[]>({
    queryKey: dashboardKeys.bars(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<BarRow[]>(`/bars?event_id=${eventId}`)
      return data
    },
    enabled: !!eventId,
  })
}

// ─── Bar stock for an event ──────────────────────────────────────────────────

export function useBarStockForEvent(eventId: string | null | undefined) {
  return useQuery<BarStockRow[]>({
    queryKey: dashboardKeys.barStock(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<BarStockRow[]>(
        `/bar-stock/by-event/${eventId}`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}

// ─── Reconciliation report (revenue aggregate + anomaly count) ───────────────

export function useReconciliation(eventId: string | null | undefined) {
  return useQuery<ReconciliationReport>({
    queryKey: dashboardKeys.reconciliation(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<ReconciliationReport>(
        `/stock-transactions/reconciliation/by-event/${eventId}`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}

// ─── Recent transactions (ledger feed) ───────────────────────────────────────
// Used for drinks_sold count + tier breakdown. We keep the limit high because
// selectors aggregate across all parent transactions for the event.

export function useTransactionsForEvent(eventId: string | null | undefined) {
  return useQuery<StockTransactionRow[]>({
    queryKey: dashboardKeys.transactions(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<StockTransactionRow[]>(
        `/stock-transactions/by-event/${eventId}?limit=500`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}

// ─── All products (catalog — for tier_rank + name joins) ─────────────────────
// Products rarely change mid-event; cache aggressively (5 min staleTime).

export function useAllProducts() {
  return useQuery<ProductRow[]>({
    queryKey: dashboardKeys.allProducts(),
    queryFn: async () => {
      const { data } = await api.get<ProductRow[]>(
        '/products?include_archived=true',
      )
      return data
    },
    staleTime: 5 * 60 * 1000,  // 5 minutes
  })
}

// ─── Burn rate (per-product consumption speed + depletion estimate) ──────
// Polls every LIVE_REFETCH_MS so the Dashboard and StockTable show fresh rates.
export interface BurnRateRow {
  product_id:            string
  bar_id:                string
  window_minutes:        number
  window_label:          'last_30m' | 'last_60m' | 'last_120m' | 'event_wide'
  actual_consumed:       string
  burn_rate_per_hour:    string
  current_qty:           number | null
  time_to_depletion_min: string | null
}

export function useBurnRatesForEvent(eventId: string | null | undefined) {
  return useQuery<BurnRateRow[]>({
    queryKey: dashboardKeys.burnRate(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<BurnRateRow[]>(
        `/stock-transactions/burn-rate/by-event/${eventId}`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}


// ─────────────────────────────────────────────────────────────────────
// DASH.6 — per-bar category totals + top-5 drinks per bar.
// Powers the redesigned Drinks Breakdown section in BarDetailOverlay.
// Backend: GET /events/{event_id}/bar-category-totals (DASH.2 endpoint).
// One query per event; each call returns ALL bars\'s breakdowns. The
// overlay filters to one bar client-side from the array.
// ─────────────────────────────────────────────────────────────────────

export interface BarCategoryBucketDTO {
  bucket:       'beer' | 'cocktails' | 'premium_cocktails' | 'wine' | 'soft_drink' | 'burgers' | 'sandwiches' | 'fried' | 'skewers' | 'pizza' | 'gelato' | 'other' | 'food'
  units:        number
  revenue_eur:  string   // backend serializes Decimal as string
}

export interface BarTopDrinkDTO {
  product_name: string
  category:     string   // granular: e.g. 'premium_cocktail', 'wine_red'
  units:        number
  revenue_eur:  string
}

export interface BarCategoryTotalsDTO {
  bar_id:             string
  bar_name:           string
  categories:         BarCategoryBucketDTO[]
  top_5_drinks:       BarTopDrinkDTO[]
  total_units:        number
  total_revenue_eur:  string
}

export interface EventBarCategoryTotalsResponse {
  event_id: string
  bars:     BarCategoryTotalsDTO[]
}

export function useBarCategoryTotals(eventId: string | null | undefined) {
  return useQuery<EventBarCategoryTotalsResponse>({
    queryKey: dashboardKeys.barCategoryTotals(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<EventBarCategoryTotalsResponse>(
        `/events/${eventId}/bar-category-totals`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}


// ─────────────────────────────────────────────────────────────────────
// DASH — event-level KPI summary (dashboard top strip).
// Backend: GET /events/{event_id}/kpi-summary (events module, Step 2).
// Authoritative rollup: drinks (100% Omar) by family + food (GROSS) by
// FoodType with the event's revenue-share % applied to yield Omar's NET
// cut. total_revenue_eur = drinks + food NET. Decimals arrive as strings.
// ─────────────────────────────────────────────────────────────────────

export type DrinkFamily = 'cocktails' | 'beer' | 'wine' | 'soft' | 'other'

export interface DrinkCategoryLineDTO {
  family:      DrinkFamily
  units:       number
  revenue_eur: string
}

export interface FoodTypeLineDTO {
  food_type:   string   // FoodType value, or 'other' for untyped food
  units:       number
  revenue_eur: string   // GROSS (pre-share)
}

export interface DrinksSummaryDTO {
  units:       number
  revenue_eur: string   // 100% Omar
  by_category: DrinkCategoryLineDTO[]
}

export interface FoodSummaryDTO {
  units:             number
  gross_revenue_eur: string
  share_pct:         number   // Omar's %, default 100
  net_revenue_eur:   string   // gross * share / 100
  by_type:           FoodTypeLineDTO[]
}

export interface EventKpiSummaryDTO {
  event_id:          string
  total_revenue_eur: string   // drinks + food NET = Omar's take
  drinks:            DrinksSummaryDTO
  food:              FoodSummaryDTO
}

export function useEventKpiSummary(eventId: string | null | undefined) {
  return useQuery<EventKpiSummaryDTO>({
    queryKey: dashboardKeys.kpiSummary(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<EventKpiSummaryDTO>(
        `/events/${eventId}/kpi-summary`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}


// ─────────────────────────────────────────────────────────────────────
// DASH — full menu performance (dashboard breakdown panel).
// Backend: GET /events/{event_id}/menu-performance (events module, Step 4).
// Every drink + food menu item with units sold (zero-sold included):
// drinks totalled per product across bars, grouped by family; food grouped
// by truck. Decimals arrive as strings.
// ─────────────────────────────────────────────────────────────────────

export interface MenuItemLineDTO {
  product_id:   string
  product_name: string
  units:        number
  revenue_eur:  string
}

export interface DrinkCategoryGroupDTO {
  family:               DrinkFamily
  items:                MenuItemLineDTO[]
  subtotal_units:       number
  subtotal_revenue_eur: string
}

export interface FoodTruckGroupDTO {
  bar_id:               string
  bar_name:             string
  items:                MenuItemLineDTO[]
  subtotal_units:       number
  subtotal_revenue_eur: string
}

export interface EventMenuPerformanceDTO {
  event_id: string
  drinks:   DrinkCategoryGroupDTO[]
  food:     FoodTruckGroupDTO[]
}

export function useMenuPerformance(eventId: string | null | undefined) {
  return useQuery<EventMenuPerformanceDTO>({
    queryKey: dashboardKeys.menuPerformance(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<EventMenuPerformanceDTO>(
        `/events/${eventId}/menu-performance`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: LIVE_REFETCH_MS,
  })
}



// ─── Phase 3: ml-depletion stock from event_category_ingredients ──
// Wired in for Sundance 14. Returns per-(bar, supplier_product) loading
// bars + per-bar aggregated stock %. Calling this endpoint ALSO fires
// depletion alerts on the backend when status crosses thresholds — so
// DashboardPage polls it at LIVE_REFETCH_MS to keep alerts firing.

export interface BarSupplierStockItemDTO {
  bar_id:              string
  bar_name:            string
  supplier_product_id: string
  item_name:           string
  dispatched_units:    number
  dispatched_ml:       number
  consumed_ml:           number
  consumed_ml_certain:   number
  consumed_ml_uncertain: number
  remaining_ml:          number
  remaining_pct:       number
  status:              'healthy' | 'low' | 'critical'
  threshold_pct_warn:  number
  threshold_pct_empty: number
  accurate:            boolean
}

export interface BarAggregatedStockDTO {
  bar_id:        string
  bar_name:      string
  dispatched_ml: number
  remaining_ml:  number
  pct:           number
  status:        'healthy' | 'low' | 'critical'
}

export interface BarSupplierStockResponseDTO {
  event_id: string
  items:    BarSupplierStockItemDTO[]
  by_bar:   BarAggregatedStockDTO[]
}

export function useBarSupplierStock(
  eventId: string | null | undefined,
  barId: string | null = null,
) {
  return useQuery<BarSupplierStockResponseDTO>({
    queryKey: ['events', eventId ?? 'none', 'bar-supplier-stock', barId ?? 'all'],
    queryFn: async () => {
      const url =
        `/events/${eventId}/bar-supplier-stock` +
        (barId ? `?bar_id=${barId}` : '')
      const { data } = await api.get<BarSupplierStockResponseDTO>(url)
      return data
    },
    enabled: Boolean(eventId),
    refetchInterval: LIVE_REFETCH_MS,
    staleTime: LIVE_REFETCH_MS / 2,
  })
}
