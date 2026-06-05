/**
 * useBulkAllocate — mutation hook for POST /bar-stock/bulk-allocate
 * (Phase C1/C2, Sundance 1 manual inventory).
 *
 * mode='set'   : qty is the TARGET allocated_qty — idempotent, used by
 *                the Allocation page grid + CSV paste-in.
 * mode='topup' : += qty, same semantics as single /bar-stock/allocate.
 *
 * On success invalidates the dashboard barStock branch for the event so
 * the monitoring InventoryPage and dashboard cards refresh.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { dashboardKeys } from '@/features/dashboard/hooks'

export interface BulkAllocateItemPayload {
  bar_id: string
  product_id: string
  qty: number
}

export interface BulkAllocatePayload {
  event_id: string
  mode: 'set' | 'topup'
  items: BulkAllocateItemPayload[]
}

export interface BulkAllocateItemError {
  index: number
  bar_id: string
  product_id: string
  error: string
}

export interface BulkAllocateResponse {
  event_id: string
  mode: string
  created: number
  updated: number
  unchanged: number
  rows: Array<{
    id: string
    bar_id: string
    product_id: string
    allocated_qty: number
    current_qty: number
    returned_qty: number
  }>
}

export function useBulkAllocate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: BulkAllocatePayload): Promise<BulkAllocateResponse> => {
      const res = await api.post<BulkAllocateResponse>('/bar-stock/bulk-allocate', payload)
      return res.data
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: dashboardKeys.barStock(vars.event_id) })
      qc.invalidateQueries({ queryKey: ['inventory'] })
    },
  })
}
