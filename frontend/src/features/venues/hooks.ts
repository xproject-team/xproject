/**
 * TanStack Query hooks for the Venues API.
 *
 * Follows the same architectural pattern as features/events/hooks.ts
 * (Decision D1: hierarchical query keys). Venues is its own domain per
 * backend contract §1.1 — isolated from events beyond the public hook API.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Venue } from '@/lib/mockData'

// ─── Query keys (hierarchical — D1) ───────────────────────────────────────────

export const venueKeys = {
  all:    ['venues'] as const,
  list:   () => [...venueKeys.all] as const,
  detail: (id: string) => [...venueKeys.all, id] as const,
} as const

// ─── Queries ──────────────────────────────────────────────────────────────────

/** GET /venues — list all venues for the current tenant (alphabetical). */
export function useVenues() {
  return useQuery({
    queryKey: venueKeys.list(),
    queryFn:  async (): Promise<Venue[]> => {
      const res = await api.get<Venue[]>('/venues')
      return res.data
    },
    // Venues rarely change during a session — cache aggressively.
    staleTime: 5 * 60 * 1000,   // 5 minutes
  })
}

/** GET /venues/{id} — single venue detail. */
export function useVenue(id: string | undefined) {
  return useQuery({
    queryKey: id ? venueKeys.detail(id) : venueKeys.all,
    queryFn:  async (): Promise<Venue> => {
      const res = await api.get<Venue>(`/venues/${id}`)
      return res.data
    },
    enabled: Boolean(id),
  })
}
