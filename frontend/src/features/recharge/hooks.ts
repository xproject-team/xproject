/**
 * TanStack Query hook for the Recharge Stations API.
 *
 * Backend: app/modules/recharge/router.py — single GET endpoint:
 *   GET /recharge-stations/by-event/{event_id} -> RechargeStationKpi[]
 *
 * Returns rolled-up aggregates for the dashboard Recharge Desk card.
 * Pattern matches features/bars/hooks.ts useBars exactly.
 *
 * Phase 2 (Jun 21 2026).
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { RechargeStationKpi } from '@/lib/mockData'

// ─── Query keys (hierarchical, matches barKeys pattern) ────────────────────

export const rechargeKeys = {
  all:     ['recharge-stations'] as const,
  byEvent: (eventId: string | undefined) =>
    [...rechargeKeys.all, 'by-event', eventId ?? 'none'] as const,
} as const

// ─── Query ─────────────────────────────────────────────────────────────────

/**
 * GET /recharge-stations/by-event/{event_id}
 *
 * Returns all recharge stations for the event with rolled-up aggregates
 * (total recharged, devices total/active, stripe_ttp / contanti split).
 * Returns [] when no station has been configured for the event.
 */
export function useRechargeStations(eventId: string | undefined) {
  return useQuery({
    queryKey: rechargeKeys.byEvent(eventId),
    queryFn:  async (): Promise<RechargeStationKpi[]> => {
      const res = await api.get<RechargeStationKpi[]>(
        `/recharge-stations/by-event/${eventId}`,
      )
      return res.data
    },
    enabled:         Boolean(eventId),
    // Recharges update live during the event — short stale window.
    staleTime:       15 * 1000,
    refetchInterval: 30 * 1000,
  })
}
