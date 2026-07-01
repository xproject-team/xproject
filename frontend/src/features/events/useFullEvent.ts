/**
 * useFullEvent — GET /events/{id}/full.
 *
 * Returns event basics + bars + referenced products + menu + allocations
 * in the wizard-round-trippable FullEventDetail shape. Used by
 * EventWizardPage in edit mode to hydrate WizardState.
 *
 * Cached under [...eventKeys.detail(id), 'full'] so it doesn't collide
 * with useEvent's summary fetch. Snapshot semantics — no refetch on
 * window focus; staleTime Infinity.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { eventKeys } from '@/features/events/hooks'
import type {
  FullEventBarInput,
  FullEventProductInput,
  FullEventMenuItemInput,
  FullEventAllocationInput,
} from '@/features/events/useCreateFullEvent'

/** The `event` field of FullEventDetail — mirrors the backend
 *  EventResponse but only the fields Chunk 3b's payload mapper needs
 *  to preserve through an edit-save (plus id/name/version for the
 *  header and optimistic-locking hygiene). */
export interface FullEventDetailEvent {
  id: string
  tenant_id: string
  name: string
  status: string
  scheduled_at: string
  scheduled_end_at: string
  venue: { id: string; name: string }
  expected_guest_count: number | null
  stripe_ragione_sociale: string | null
  staff_arrival_time: string | null
  wristband_qty_per_type: Record<string, number> | null
  topup_denominations_user: number[] | null
  topup_denominations_staff: number[] | null
  refund_min_credit_cents: number | null
  refund_fee_cents: number | null
  refund_window_open_at: string | null
  refund_window_close_at: string | null
  food_revenue_share_pct: number | null
  version: number
}

/** Bag of tenant-global product data + menu + allocations that the
 *  wizard UI never edits directly. Stashed on WizardState as
 *  `_hydration` in edit mode; Chunk 3b's payload mapper reads it and
 *  remaps bar_index by current bar ordering when writing the PUT. */
export interface FullEventHydrationBag {
  products: FullEventProductInput[]
  menu: FullEventMenuItemInput[]
  allocations: FullEventAllocationInput[]
}

/** Response shape of GET /events/{id}/full — mirrors backend
 *  FullEventDetail. */
export interface FullEventDetail {
  event: FullEventDetailEvent
  bars: FullEventBarInput[]
  products: FullEventProductInput[]
  menu: FullEventMenuItemInput[]
  allocations: FullEventAllocationInput[]
}

const fullKey = (id: string) => [...eventKeys.detail(id), 'full'] as const

export function useFullEvent(eventId: string | null) {
  return useQuery({
    queryKey: eventId ? fullKey(eventId) : ['events', 'full', 'disabled'],
    queryFn: async (): Promise<FullEventDetail> => {
      const res = await api.get<FullEventDetail>(`/events/${eventId}/full`)
      return res.data
    },
    enabled: Boolean(eventId),
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })
}
