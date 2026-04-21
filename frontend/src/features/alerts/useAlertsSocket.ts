/**
 * useAlertsSocket — real-time alert push via WebSocket.
 *
 * Opens a WebSocket to /api/v1/ws/alerts/{eventId}?token=<JWT>. The
 * backend publishes an "alert_changed" frame to Redis every time an
 * alert is created, acknowledged, auto-resolved, or expired; that push
 * fans out to all WS subscribers for the event.
 *
 * On any incoming frame, we simply invalidate the alerts cache so every
 * mounted hook (useAlertsForEvent, useAlertsCount, useAlertsCountByBar)
 * refetches fresh data via HTTP. This keeps the WS frame tiny (just
 * "something changed" + ids) and avoids duplicating business logic
 * between REST and WS.
 *
 * Fallback: the three data-fetch hooks still poll every 10 seconds.
 * If the WS connection drops, the UI stays correct (eventually);
 * when the WS reconnects, invalidation resumes immediately.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { getToken } from '@/lib/auth'
import { useWebSocket } from '@/lib/ws'

import { alertsKeys } from './useAlerts'

interface IncomingFrame {
  type:      string
  event_id?: string
  alert_id?: string
}

export function useAlertsSocket(eventId: string | null | undefined) {
  const qc = useQueryClient()
  const token = getToken()
  const url =
    eventId && token
      ? `/api/v1/ws/alerts/${eventId}?token=${encodeURIComponent(token)}`
      : null

  // Stable handler ref so useWebSocket doesn't tear down and recreate the
  // socket on every render (same critical pattern used by useChatSocket).
  const handlerRef = useRef<(raw: string) => void>(() => {})
  handlerRef.current = function handleMessage(raw: string) {
    let frame: IncomingFrame
    try {
      frame = JSON.parse(raw) as IncomingFrame
    } catch {
      return // malformed frame, ignore
    }
    // We don't distinguish alert_changed vs other types yet — any frame
    // triggers a cache invalidation, since the backend only publishes
    // meaningful state changes.
    if (frame.type) {
      qc.invalidateQueries({ queryKey: alertsKeys.all })
    }
  }

  const stableHandler = useRef<(raw: string) => void>((raw) =>
    handlerRef.current(raw),
  ).current

  const { isConnected } = useWebSocket(url, { onMessage: stableHandler })

  // Expose connection state for debugging / indicators if a consumer wants it.
  useEffect(() => {
    if (eventId) {
      // eslint-disable-next-line no-console
      console.debug(
        `[alerts ws] event=${eventId} connected=${isConnected}`,
      )
    }
  }, [eventId, isConnected])

  return { isConnected }
}
