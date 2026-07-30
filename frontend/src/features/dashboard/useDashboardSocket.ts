/**
 * useDashboardSocket — real-time push for the bar dashboard.
 *
 * Opens a WebSocket to /api/v1/ws/events/{eventId}?token=<JWT>. The
 * backend subscribes the socket to:
 *   - event:{eventId}                  (existing channel — sale events,
 *                                       general event-scoped updates)
 *   - stock:{eventId}:{user.bar_id}    (added in sub-patch 3b.6 — bar
 *                                       stock + transaction changes)
 *
 * Any incoming frame triggers TanStack Query invalidations on the
 * dashboard's data-source keys so KPI tiles, alerts, and the
 * transactions table re-fetch and re-render with fresh data.
 *
 * Polling fallback: each useDashboardSocket consumer's underlying hook
 * (useBarStockForEvent, useTransactionsForEvent, etc.) keeps its 10s
 * refetchInterval. The WebSocket is the FAST path; polling is the
 * SLOW safety net. If the WS is dead the dashboard still updates,
 * just at 10s granularity instead of <200ms.
 *
 * Spec: docs/bar-dashboard-spec.md S8.2 + S8.3.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { getToken } from '@/lib/auth'
import { useWebSocket } from '@/lib/ws'

import { dashboardKeys } from './hooks'
import { alertsKeys } from '@/features/alerts/useAlerts'
import { customerIntelKeys } from '@/features/customer-intelligence/useCustomerIntelligence'

interface IncomingFrame {
  type?:        string
  event_id?:    string
  bar_id?:      string
  product_id?:  string
}

export interface DashboardSocketState {
  /** True when the WS is connected and frames are flowing. */
  isConnected: boolean
}

/**
 * Connect to the event WebSocket for the live event the dashboard is
 * showing. Returns connection state for the live-sync indicator.
 *
 * @param eventId  — the event being viewed; null disables the socket
 */
export function useDashboardSocket(
  eventId: string | null | undefined,
): DashboardSocketState {
  const qc = useQueryClient()
  const token = getToken()

  const url =
    eventId && token
      ? `/api/v1/ws/events/${eventId}?token=${encodeURIComponent(token)}`
      : null

  // Stable handler ref so useWebSocket doesn't tear down + recreate the
  // socket on every render (same critical pattern as useAlertsSocket /
  // useChatSocket — without this, the socket count grows unbounded).
  const handlerRef = useRef<(raw: string) => void>(() => {})
  handlerRef.current = function handleMessage(raw: string) {
    let frame: IncomingFrame
    try {
      frame = JSON.parse(raw) as IncomingFrame
    } catch {
      return // malformed frame, ignore
    }

    // We invalidate ALL dashboard-related caches on any frame for v1.0.
    // Future polish: switch on frame.type and only invalidate the
    // affected slice (e.g. only stock keys for stock:* messages).
    // customer-intelligence.refreshed (Day 4) arrives on this same
    // event:{eventId} channel, pushed every 5 min for LIVE events by
    // the arq refresh job — same "background compute, thin notify,
    // frontend refetches" pattern as everything else here.
    if (frame.type) {
      qc.invalidateQueries({ queryKey: dashboardKeys.all })
      qc.invalidateQueries({ queryKey: alertsKeys.all })
      qc.invalidateQueries({ queryKey: customerIntelKeys.all })
    }
  }

  const stableHandler = useRef<(raw: string) => void>((raw) =>
    handlerRef.current(raw),
  ).current

  const { isConnected } = useWebSocket(url, { onMessage: stableHandler })

  // Optional debug log so we can see connection lifecycle without
  // opening DevTools on every page load.
  useEffect(() => {
    if (eventId) {
      // eslint-disable-next-line no-console
      console.debug(
        `[dashboard ws] event=${eventId} connected=${isConnected}`,
      )
    }
  }, [eventId, isConnected])

  return { isConnected }
}
