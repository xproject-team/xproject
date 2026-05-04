/**
 * TanStack Query hooks for the Bars API.
 *
 * Backend: app/modules/bars/router.py — full CRUD + filters by event_id.
 * Pattern matches features/venues/hooks.ts exactly (decision D1: hierarchical
 * query keys for surgical invalidation).
 *
 * Hooks exported:
 *   useBars(eventId?)          — list (optionally filtered to one event)
 *   useBar(id)                 — single detail
 *   useCreateBar()             — POST /bars
 *   useUpdateBar()             — PATCH /bars/{id}
 *   useDeleteBar()             — DELETE /bars/{id}  (hard delete, with confirm modal)
 *
 * On success, mutations invalidate the bars list so the UI auto-refreshes.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { BarRow, BarType } from '@/lib/mockData'

// ─── Request payloads ─────────────────────────────────────────────────────────

export interface BarCreatePayload {
  event_id:          string
  name:              string
  bar_type:          BarType
  slesh_negozio_id?: string | null
  is_active?:        boolean
}

export interface BarUpdatePayload {
  name?:             string
  bar_type?:         BarType
  slesh_negozio_id?: string | null
  is_active?:        boolean
}

// ─── Query keys (hierarchical — D1) ───────────────────────────────────────────

export const barKeys = {
  all:    ['bars'] as const,
  list:   (eventId: string | undefined) =>
    [...barKeys.all, 'list', eventId ?? 'all'] as const,
  detail: (id: string) => [...barKeys.all, id] as const,
} as const

// ─── Queries ──────────────────────────────────────────────────────────────────

/**
 * GET /bars — list bars, optionally filtered by event_id.
 *
 * When eventId is undefined the backend returns all bars for the tenant
 * across all events. When set, returns only that event's bars.
 */
export function useBars(eventId?: string) {
  return useQuery({
    queryKey: barKeys.list(eventId),
    queryFn:  async (): Promise<BarRow[]> => {
      const url = eventId ? `/bars?event_id=${eventId}` : '/bars'
      const res = await api.get<BarRow[]>(url)
      return res.data
    },
    // Bars rarely change during a session — cache for 2 minutes.
    staleTime: 2 * 60 * 1000,
  })
}

/** GET /bars/{id} — single bar detail. */
export function useBar(id: string | undefined) {
  return useQuery({
    queryKey: id ? barKeys.detail(id) : barKeys.all,
    queryFn:  async (): Promise<BarRow> => {
      const res = await api.get<BarRow>(`/bars/${id}`)
      return res.data
    },
    enabled: Boolean(id),
  })
}

// ─── Mutations ────────────────────────────────────────────────────────────────

/** POST /bars — create a new bar for an event. */
export function useCreateBar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: BarCreatePayload): Promise<BarRow> => {
      const res = await api.post<BarRow>('/bars', payload)
      return res.data
    },
    onSuccess: (newBar) => {
      // Invalidate every list query (any eventId) — newBar might match any of them
      queryClient.invalidateQueries({ queryKey: barKeys.all })
      // Seed the detail cache so the redirect-to-detail call is instant
      queryClient.setQueryData(barKeys.detail(newBar.id), newBar)
    },
  })
}

/** PATCH /bars/{id} — update a bar. */
export function useUpdateBar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (args: { id: string; payload: BarUpdatePayload }): Promise<BarRow> => {
      const res = await api.patch<BarRow>(`/bars/${args.id}`, args.payload)
      return res.data
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: barKeys.all })
      queryClient.setQueryData(barKeys.detail(updated.id), updated)
    },
  })
}

/** DELETE /bars/{id} — hard delete (cascades to bar_stock + transactions). */
export function useDeleteBar() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(`/bars/${id}`)
    },
    onSuccess: (_void, id) => {
      queryClient.invalidateQueries({ queryKey: barKeys.all })
      queryClient.removeQueries({ queryKey: barKeys.detail(id) })
    },
  })
}
