/**
 * Alerts TanStack Query hooks.
 *
 * Contract-first: interfaces mirror backend AlertResponse exactly (snake_case,
 * matches Pydantic schemas.py). Three hooks:
 *
 *   useAlertsForEvent  — list alerts for an event, polls every 10s
 *   useAlertsCount     — {severity: count} for the top-bar badge, polls every 10s
 *   useAcknowledgeAlert — mutation; optimistic lock via version; invalidates all
 *
 * No WebSocket yet — the 10-second polling is demo-grade and avoids the
 * complexity of WS reconnect logic in this commit. WS push ships later.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

// ─── Types (match backend schemas.py AlertResponse 1:1) ──────────────────────

export type AlertType = 'depletion' | 'anomaly' | 'discrepancy' | 'system'
export type AlertSeverity = 'info' | 'warning' | 'critical' | 'anomaly'
export type AlertAudience = 'owner_only' | 'owner_and_manager'
export type AlertLifecycleState =
  | 'active'
  | 'acknowledged'
  | 'auto_resolved'
  | 'expired'

export interface AlertRow {
  id: string
  tenant_id: string
  event_id: string
  bar_id: string
  product_id: string | null
  alert_type: AlertType
  severity: AlertSeverity
  audience: AlertAudience
  title: string
  message: string
  suggested_action: string | null
  ai_advisory: string | null
  context_json: Record<string, unknown>
  created_at: string
  acknowledged_at: string | null
  acknowledged_by_user_id: string | null
  auto_resolved_at: string | null
  expired_at: string | null
  lifecycle_state: AlertLifecycleState
  version: number
}

export interface AlertListResponse {
  items: AlertRow[]
  total: number
}

export interface AlertCountResponse {
  info: number
  warning: number
  critical: number
  anomaly: number
  total: number
}

// ─── Query keys (hierarchical, for surgical invalidation) ────────────────────

export const alertsKeys = {
  all: ['alerts'] as const,
  byEvent: (eventId: string) =>
    [...alertsKeys.all, 'byEvent', eventId] as const,
  count: (eventId: string) =>
    [...alertsKeys.all, 'count', eventId] as const,
  detail: (alertId: string) =>
    [...alertsKeys.all, 'detail', alertId] as const,
}

const ALERTS_POLL_MS = 10_000

// ─── List alerts for an event ────────────────────────────────────────────────

export function useAlertsForEvent(
  eventId: string | null | undefined,
  options?: { onlyActive?: boolean; severity?: AlertSeverity },
) {
  const onlyActive = options?.onlyActive ?? true
  const severity = options?.severity
  return useQuery<AlertListResponse>({
    queryKey: [...alertsKeys.byEvent(eventId ?? 'none'),
      onlyActive, severity ?? 'any'],
    queryFn: async () => {
      const { data } = await api.get<AlertListResponse>(
        `/alerts/by-event/${eventId}`,
        {
          params: {
            only_active: onlyActive,
            ...(severity ? { severity } : {}),
          },
        },
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: ALERTS_POLL_MS,
  })
}

// ─── Severity counts (for top-bar badge) ─────────────────────────────────────

export function useAlertsCount(eventId: string | null | undefined) {
  return useQuery<AlertCountResponse>({
    queryKey: alertsKeys.count(eventId ?? 'none'),
    queryFn: async () => {
      const { data } = await api.get<AlertCountResponse>(
        `/alerts/by-event/${eventId}/count`,
      )
      return data
    },
    enabled: !!eventId,
    refetchInterval: ALERTS_POLL_MS,
  })
}

// ─── Acknowledge (mutation) ──────────────────────────────────────────────────

export interface AcknowledgePayload {
  alert_id: string
  version: number
}

export function useAcknowledgeAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ alert_id, version }: AcknowledgePayload) => {
      const { data } = await api.patch(
        `/alerts/${alert_id}/acknowledge`,
        { version },
      )
      return data
    },
    // On success, invalidate every alerts query — safe and simple. TanStack
    // Query refetches only the queries currently mounted by a component.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: alertsKeys.all })
    },
  })
}