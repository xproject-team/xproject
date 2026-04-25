/**
 * Warehouse TanStack Query hooks.
 *
 * Contract-first: TypeScript interfaces mirror backend Pydantic schemas.py
 * (snake_case throughout). Every hook call translates directly to one REST
 * endpoint from docs/warehouse-module-spec.md §8.
 *
 * Hero feature is invoice reconciliation. Everything else (inventory, scans,
 * allocations) supports that loop.
 *
 * Hooks provided:
 *   Inventory dashboard:
 *     useInventoryKpis         — 5-metric header tile data
 *     useInventoryGrid         — product grid with per-product risk
 *     useActivityFeed          — last N scans for side panel
 *     usePendingReviewQueue    — Owner approval queue
 *
 *   Invoice lifecycle:
 *     useInvoices              — list with status filter
 *     usePendingDeliveries     — dashboard strip (EXPECTED/SCANNING/PAUSED)
 *     useInvoice               — detail view
 *     useCreateInvoice         — POST /invoices
 *     useUpdateInvoice         — PATCH (only while EXPECTED)
 *     useStartScan / usePauseScan / useResumeScan / useCloseScan
 *     useArchiveInvoice / useDisputeInvoice
 *     useInvoiceReport         — live DiscrepancyReport at any state
 *
 *   Scans (hot path):
 *     useSubmitScan            — POST /scans (role enforced server-side)
 *     useResolveBarcode        — lookup before submit
 *     useApprovePendingScan / useRejectPendingScan
 *
 *   Allocations:
 *     useEventAllocations      — list reservations for an event
 *     useUpsertEventAllocations — Owner atomic update
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'

import { api } from '@/lib/api'

// ─── Types (match backend schemas.py 1:1) ────────────────────────────────────

export type InvoiceStatus =
  | 'EXPECTED'
  | 'SCANNING'
  | 'PAUSED'
  | 'VERIFIED'
  | 'DISCREPANCY'
  | 'DISPUTED'
  | 'CLOSED'

export type ScanType =
  | 'INTAKE'
  | 'DISPATCH'
  | 'RETURN'
  | 'ADJUSTMENT'
  | 'INSPECT'
  | 'CONSUMED'

export type ScannerRole = 'owner' | 'manager' | 'bartender' | 'warehouse_keeper'
export type InvoiceLineKind = 'catalog_product' | 'miscellaneous'
export type DiscrepancyLineStatus = 'match' | 'short' | 'extra' | 'unexpected'
export type OverallDiscrepancyStatus = 'match' | 'discrepancy' | 'dispute_opened'

// Decimal comes over the wire as a string (Pydantic default) — consumers
// convert with Number() or a Decimal library where precision matters.
export type Decimal = string

// ─── Invoice family ──────────────────────────────────────────────────────────

export interface InvoiceItemResponse {
  id: string
  invoice_id: string
  kind: InvoiceLineKind
  product_id: string | null
  miscellaneous_description: string | null
  expected_qty: Decimal
  unit_price_cents: number | null
  line_total_cents: number | null
  created_at: string
  updated_at: string
}

export interface InvoiceItemCreate {
  kind: InvoiceLineKind
  product_id?: string | null
  miscellaneous_description?: string | null
  expected_qty: number | string
  unit_price_cents?: number | null
}

export interface InvoiceResponse {
  id: string
  tenant_id: string
  invoice_number: string | null
  supplier_name: string
  expected_arrival_date: string
  status: InvoiceStatus
  scan_started_at: string | null
  scan_closed_at: string | null
  closed_by: string | null
  notes: string | null
  items: InvoiceItemResponse[]
  created_at: string
  updated_at: string
}

export interface InvoiceSummary {
  id: string
  invoice_number: string | null
  supplier_name: string
  expected_arrival_date: string
  status: InvoiceStatus
  items_count: number
  total_expected_cents: number | null
  scan_started_at: string | null
  created_at: string
}

export interface InvoiceCreateRequest {
  invoice_number?: string | null
  supplier_name: string
  expected_arrival_date: string
  notes?: string | null
  items: InvoiceItemCreate[]
}

export interface InvoiceUpdateRequest {
  invoice_number?: string | null
  supplier_name?: string
  expected_arrival_date?: string
  notes?: string | null
}

// ─── Scan family ─────────────────────────────────────────────────────────────

export interface ScanResponse {
  id: string
  tenant_id: string
  scan_type: ScanType
  invoice_id: string | null
  product_id: string | null
  product_name: string | null
  barcode_raw: string | null
  qty: Decimal
  event_id: string | null
  bar_id: string | null
  bar_name: string | null
  is_unexpected: boolean
  pending_review: boolean
  scanned_by_user_id: string | null
  scanned_by_user_name: string | null
  scanned_by_role: ScannerRole
  scanned_at: string
}

export interface ScanCreateRequest {
  scan_type: ScanType
  product_id?: string | null
  barcode_raw?: string | null
  qty?: number | string
  invoice_id?: string | null
  event_id?: string | null
  bar_id?: string | null
}

export interface BarcodeResolveResponse {
  status: 'known' | 'unknown'
  barcode: string
  product_id: string | null
  product_name: string | null
}

// ─── Dashboard read types ────────────────────────────────────────────────────

export interface InventoryKpis {
  total_items: number
  total_quantity: Decimal
  products_at_risk: number
  active_allocations: Decimal
  pending_reviews: number
}

export interface InventoryRow {
  product_id: string
  product_name: string
  category: string | null
  brand: string | null
  current_qty: Decimal
  allocated_qty: Decimal
  available_qty: Decimal
  low_stock_threshold: Decimal | null
  is_at_risk: boolean
  last_movement_at: string | null
}

export interface ActivityFeedRow {
  id: string
  scan_type: ScanType
  product_name: string | null
  qty: Decimal
  scanned_by_user_name: string | null
  scanned_by_role: ScannerRole
  scanned_at: string
  is_unexpected: boolean
  pending_review: boolean
}

// ─── Discrepancy report (the hero response) ──────────────────────────────────

export interface DiscrepancyLine {
  product_id: string | null
  product_name: string
  expected_qty: Decimal
  scanned_qty: Decimal
  delta: Decimal
  status: DiscrepancyLineStatus
  unit_price_cents: number | null
  value_delta_cents: number | null
}

export interface DiscrepancyReport {
  invoice_id: string
  supplier_name: string
  computed_at: string
  lines: DiscrepancyLine[]
  total_expected_cents: number | null
  total_scanned_value_cents: number | null
  total_delta_cents: number | null
  has_shortage: boolean
  has_unexpected: boolean
  overall_status: OverallDiscrepancyStatus
}

// ─── Allocations ─────────────────────────────────────────────────────────────

export interface AllocationResponse {
  id: string
  event_id: string
  product_id: string
  product_name: string | null
  reserved_qty: Decimal
  dispatched_qty: Decimal
  remaining_qty: Decimal
}

export interface AllocationUpsertItem {
  product_id: string
  reserved_qty: number | string
}

// ─── Query keys (centralized for invalidation) ───────────────────────────────

export const warehouseKeys = {
  all: ['warehouse'] as const,
  kpis: () => [...warehouseKeys.all, 'kpis'] as const,
  inventory: () => [...warehouseKeys.all, 'inventory'] as const,
  activity: (limit: number) =>
    [...warehouseKeys.all, 'activity', limit] as const,
  pendingReview: () => [...warehouseKeys.all, 'pending-review'] as const,
  invoices: (status?: InvoiceStatus) =>
    [...warehouseKeys.all, 'invoices', status ?? 'all'] as const,
  pendingDeliveries: () =>
    [...warehouseKeys.all, 'invoices', 'pending-deliveries'] as const,
  invoice: (id: string) => [...warehouseKeys.all, 'invoice', id] as const,
  invoiceReport: (id: string) =>
    [...warehouseKeys.all, 'invoice-report', id] as const,
  allocations: (eventId: string) =>
    [...warehouseKeys.all, 'allocations', eventId] as const,
}

// ═════════════════════════════════════════════════════════════════════════════
// DASHBOARD READ HOOKS
// ═════════════════════════════════════════════════════════════════════════════

export function useInventoryKpis(
  options?: Omit<UseQueryOptions<InventoryKpis>, 'queryKey' | 'queryFn'>,
) {
  return useQuery<InventoryKpis>({
    queryKey: warehouseKeys.kpis(),
    queryFn: async () => {
      const { data } = await api.get<InventoryKpis>(
        '/warehouse/inventory/kpis',
      )
      return data
    },
    staleTime: 30_000,
    ...options,
  })
}

export function useInventoryGrid() {
  return useQuery<InventoryRow[]>({
    queryKey: warehouseKeys.inventory(),
    queryFn: async () => {
      const { data } = await api.get<InventoryRow[]>('/warehouse/inventory')
      return data
    },
    staleTime: 30_000,
  })
}

export function useActivityFeed(limit = 20) {
  return useQuery<ActivityFeedRow[]>({
    queryKey: warehouseKeys.activity(limit),
    queryFn: async () => {
      const { data } = await api.get<ActivityFeedRow[]>(
        '/warehouse/inventory/activity',
        { params: { limit } },
      )
      return data
    },
    staleTime: 15_000,
  })
}

export function usePendingReviewQueue() {
  return useQuery<ScanResponse[]>({
    queryKey: warehouseKeys.pendingReview(),
    queryFn: async () => {
      const { data } = await api.get<ScanResponse[]>(
        '/warehouse/inventory/pending-review',
      )
      return data
    },
    staleTime: 15_000,
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// INVOICE HOOKS
// ═════════════════════════════════════════════════════════════════════════════

export function useInvoices(filters?: {
  status?: InvoiceStatus
  limit?: number
}) {
  return useQuery<InvoiceSummary[]>({
    queryKey: warehouseKeys.invoices(filters?.status),
    queryFn: async () => {
      const { data } = await api.get<InvoiceSummary[]>('/warehouse/invoices', {
        params: filters,
      })
      return data
    },
    staleTime: 15_000,
  })
}

export function usePendingDeliveries() {
  return useQuery<InvoiceSummary[]>({
    queryKey: warehouseKeys.pendingDeliveries(),
    queryFn: async () => {
      const { data } = await api.get<InvoiceSummary[]>(
        '/warehouse/invoices/pending',
      )
      return data
    },
    staleTime: 15_000,
  })
}

export function useInvoice(invoiceId: string | null) {
  return useQuery<InvoiceResponse>({
    queryKey: invoiceId
      ? warehouseKeys.invoice(invoiceId)
      : warehouseKeys.invoice(''),
    queryFn: async () => {
      const { data } = await api.get<InvoiceResponse>(
        `/warehouse/invoices/${invoiceId}`,
      )
      return data
    },
    enabled: invoiceId !== null,
  })
}

export function useInvoiceReport(invoiceId: string | null) {
  return useQuery<DiscrepancyReport>({
    queryKey: invoiceId
      ? warehouseKeys.invoiceReport(invoiceId)
      : warehouseKeys.invoiceReport(''),
    queryFn: async () => {
      const { data } = await api.get<DiscrepancyReport>(
        `/warehouse/invoices/${invoiceId}/report`,
      )
      return data
    },
    enabled: invoiceId !== null,
  })
}

export function useCreateInvoice() {
  const qc = useQueryClient()
  return useMutation<InvoiceResponse, Error, InvoiceCreateRequest>({
    mutationFn: async (body) => {
      const { data } = await api.post<InvoiceResponse>(
        '/warehouse/invoices',
        body,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useUpdateInvoice(invoiceId: string) {
  const qc = useQueryClient()
  return useMutation<InvoiceResponse, Error, InvoiceUpdateRequest>({
    mutationFn: async (body) => {
      const { data } = await api.patch<InvoiceResponse>(
        `/warehouse/invoices/${invoiceId}`,
        body,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

// Simple state-transition hooks — all follow the same pattern
function invoiceTransitionHook(endpoint: string) {
  return (invoiceId: string) => {
    const qc = useQueryClient()
    return useMutation<InvoiceResponse, Error, void>({
      mutationFn: async () => {
        const { data } = await api.post<InvoiceResponse>(
          `/warehouse/invoices/${invoiceId}/${endpoint}`,
        )
        return data
      },
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: warehouseKeys.all })
      },
    })
  }
}

export const useStartScan = invoiceTransitionHook('start-scan')
export const usePauseScan = invoiceTransitionHook('pause')
export const useResumeScan = invoiceTransitionHook('resume')
export const useArchiveInvoice = invoiceTransitionHook('archive')

export function useCloseScan(invoiceId: string) {
  const qc = useQueryClient()
  return useMutation<DiscrepancyReport, Error, void>({
    mutationFn: async () => {
      const { data } = await api.post<DiscrepancyReport>(
        `/warehouse/invoices/${invoiceId}/close`,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useDisputeInvoice(invoiceId: string) {
  const qc = useQueryClient()
  return useMutation<InvoiceResponse, Error, { reason: string }>({
    mutationFn: async (body) => {
      const { data } = await api.post<InvoiceResponse>(
        `/warehouse/invoices/${invoiceId}/dispute`,
        body,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// SCAN HOOKS (the hot path)
// ═════════════════════════════════════════════════════════════════════════════

export function useSubmitScan() {
  const qc = useQueryClient()
  return useMutation<ScanResponse, Error, ScanCreateRequest>({
    mutationFn: async (body) => {
      const { data } = await api.post<ScanResponse>('/warehouse/scans', body)
      return data
    },
    onSuccess: () => {
      // Invalidate everything — scans affect KPIs, inventory, activity, invoices
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useResolveBarcode() {
  // Not a query — one-shot lookup triggered by the camera UI
  return useMutation<BarcodeResolveResponse, Error, { barcode: string }>({
    mutationFn: async (body) => {
      const { data } = await api.post<BarcodeResolveResponse>(
        '/warehouse/barcode/resolve',
        body,
      )
      return data
    },
  })
}

export function useApprovePendingScan() {
  const qc = useQueryClient()
  return useMutation<ScanResponse, Error, string>({
    mutationFn: async (scanId) => {
      const { data } = await api.post<ScanResponse>(
        `/warehouse/scans/${scanId}/approve`,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

export function useRejectPendingScan() {
  const qc = useQueryClient()
  return useMutation<ScanResponse, Error, string>({
    mutationFn: async (scanId) => {
      const { data } = await api.post<ScanResponse>(
        `/warehouse/scans/${scanId}/reject`,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}

// ═════════════════════════════════════════════════════════════════════════════
// ALLOCATION HOOKS
// ═════════════════════════════════════════════════════════════════════════════

export function useEventAllocations(eventId: string | null) {
  return useQuery<AllocationResponse[]>({
    queryKey: eventId
      ? warehouseKeys.allocations(eventId)
      : warehouseKeys.allocations(''),
    queryFn: async () => {
      const { data } = await api.get<AllocationResponse[]>(
        `/warehouse/allocations/event/${eventId}`,
      )
      return data
    },
    enabled: eventId !== null,
  })
}

export function useUpsertEventAllocations(eventId: string) {
  const qc = useQueryClient()
  return useMutation<AllocationResponse[], Error, AllocationUpsertItem[]>({
    mutationFn: async (items) => {
      const { data } = await api.patch<AllocationResponse[]>(
        `/warehouse/allocations/event/${eventId}`,
        items,
      )
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: warehouseKeys.all })
    },
  })
}
