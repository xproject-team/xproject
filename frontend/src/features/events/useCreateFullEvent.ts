/**
 * useCreateFullEvent — mutation for POST /api/v1/events/full (Phase D wizard).
 *
 * Creates a complete event atomically: event + bars + products + menu
 * (event_products) + starting allocations (bar_stock). All-or-nothing on the
 * backend, so a failed call never leaves a half-created event.
 *
 * menu/allocations reference bars/products BY INDEX into the bars[]/products[]
 * arrays, since their UUIDs don't exist until the server creates them.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { eventKeys } from '@/features/events/hooks'

export interface FullEventBarInput {
  name: string
  slesh_negozio_id?: string | null
  bar_type: string
  device_count: number
  slesh_category?: string | null
  is_active: boolean
}

export interface FullEventProductInput {
  name: string
  product_type: 'drink' | 'food' | 'ingredient' | 'supply'
  category?: string | null
  tier_rank?: number | null
  unit: string
  default_price_cents?: number | null
  iva_pct?: number | null
  cauzione_cents?: number | null
}

export interface FullEventMenuItemInput {
  bar_index: number
  product_index: number
  price_cents: number
  tier_rank_override?: number | null
  is_available: boolean
}

export interface FullEventAllocationInput {
  bar_index: number
  product_index: number
  qty: number
}

export interface FullEventCreatePayload {
  event: {
    name: string
    venue_id: string
    scheduled_at: string
    scheduled_end_at: string
    expected_guest_count?: number | null
    stripe_ragione_sociale?: string | null
    staff_arrival_time?: string | null
    wristband_qty_per_type?: Record<string, number> | null
    topup_denominations_user?: number[] | null
    topup_denominations_staff?: number[] | null
    refund_min_credit_cents?: number | null
    refund_fee_cents?: number | null
    refund_window_open_at?: string | null
    refund_window_close_at?: string | null
  }
  bars: FullEventBarInput[]
  products: FullEventProductInput[]
  menu: FullEventMenuItemInput[]
  allocations: FullEventAllocationInput[]
}

export interface FullEventItemError {
  section: 'bars' | 'products' | 'menu' | 'allocations'
  index: number
  error: string
}

export interface FullEventCreateResult {
  event: { id: string; name: string; status: string }
  bars_created: number
  products_created: number
  products_reused: number
  menu_items_created: number
  allocations_created: number
}

export function useCreateFullEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: FullEventCreatePayload): Promise<FullEventCreateResult> => {
      const res = await api.post<FullEventCreateResult>('/events/full', payload)
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: eventKeys.list() })
    },
  })
}

/** Pull the sectioned validation errors out of a 422 from /events/full. */
export function extractFullEventErrors(err: unknown): FullEventItemError[] | null {
  const detail = (err as {
    response?: { data?: { detail?: { error?: string; items?: FullEventItemError[] } } }
  })?.response?.data?.detail
  if (detail?.error === 'full_event_validation_failed' && detail.items) {
    return detail.items
  }
  return null
}


/** PUT /events/{id}/full — restructure a DRAFT event from the wizard. */
export function useUpdateFullEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { eventId: string; payload: FullEventCreatePayload }): Promise<FullEventCreateResult> => {
      const res = await api.put<FullEventCreateResult>(`/events/${args.eventId}/full`, args.payload)
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: eventKeys.list() })
    },
  })
}
