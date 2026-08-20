/**
 * AlertsPage — design-system conversion (Day 11 Phase 3).
 *
 * Same data/behavior as before (useAlertsForEvent + useAcknowledgeAlert,
 * the owner-only Anomaly Detection section gated by usePermissions) —
 * this is a UI-only restyle onto the dark design system used by
 * Events/Bars/Catalog: centred layout, PageHeader, Badge, EmptyState,
 * MetricTile, dark surfaces/borders/tokens throughout. No hook, type, or
 * backend change.
 *
 * lifecycle_state note: the backend now also returns 'resolved' (manual
 * resolve, migration ag1) alongside resolved_at/resolved_by_user_id —
 * shipped in Phase 2, but the shared useAlerts.ts hook type hasn't been
 * widened for it yet (that would be a hook/type change, out of scope for
 * a UI-only pass). AlertRowResolved below widens the type LOCALLY to this
 * page only, same pattern as the acknowledge-version field elsewhere in
 * this codebase — reads data the API already sends, changes no contract.
 */
import { useCallback, useMemo, useState } from 'react'

import { formatRelativeTime } from '@/lib/utils'
import { usePermissions } from '@/features/auth/usePermissions'
import { useLiveEvent } from '@/features/dashboard/hooks'
import { useAlertsForEvent, useAcknowledgeAlert } from '@/features/alerts/useAlerts'
import type { AlertRow, AlertLifecycleState, AlertSeverity } from '@/features/alerts/useAlerts'
import { Badge, Button, EmptyState, MetricTile, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'

type AlertRowResolved = AlertRow & {
  resolved_at: string | null
  lifecycle_state: AlertLifecycleState | 'resolved'
}

// ─── Possible-causes hints for anomaly alerts ─────────────────────────
// Pre-existing placeholder content (no per-alert cause data from the
// backend yet) — kept as-is, just restyled.
const DEFAULT_CAUSES = ['Unusual demand pattern', 'Possible miscounting', 'Staff or promotional factor']

// ─── Severity → accent color / badge variant ──────────────────────────

const SEVERITY_COLOR: Record<AlertSeverity, string> = {
  critical: 'var(--v-pink)',
  warning: 'var(--v-amber)',
  info: 'var(--v-cyan)',
  anomaly: 'var(--v-violet)',
}

const SEVERITY_BADGE: Record<AlertSeverity, BadgeVariant> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
  anomaly: 'violet',
}

const CLOSED_LABEL: Record<string, string> = {
  acknowledged: 'Acknowledged',
  resolved: 'Resolved',
  auto_resolved: 'Auto-resolved',
  expired: 'Expired',
}

// ─── Filter pills ───────────────────────────────────────────────────────

type FilterKey = 'all' | 'critical' | 'warning' | 'acknowledged'

const FILTER_LABELS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'critical', label: 'Critical' },
  { key: 'warning', label: 'Warning' },
  { key: 'acknowledged', label: 'Acknowledged' },
]

function FilterPill({ label, count, isActive, onClick }: {
  label: string
  count: number
  isActive: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="text-xs font-medium px-3 py-1.5 rounded-full transition-colors"
      style={{
        background: isActive ? 'rgba(0, 229, 212, 0.12)' : 'var(--v-surface)',
        color: isActive ? 'var(--v-cyan)' : 'var(--v-text-muted)',
        border: `0.5px solid ${isActive ? 'var(--v-cyan)' : 'var(--v-border)'}`,
      }}
    >
      {label} <span className="opacity-75">({count})</span>
    </button>
  )
}

// ─── Alert row ────────────────────────────────────────────────────────

function AlertListRow({
  alert,
  onAcknowledge,
  acknowledging,
}: {
  alert: AlertRowResolved
  onAcknowledge: (id: string, version: number) => void
  acknowledging: boolean
}) {
  const isActive = alert.lifecycle_state === 'active'
  const barName = (alert.context_json?.bar_name as string) ?? 'Unknown bar'
  const accentColor = isActive ? SEVERITY_COLOR[alert.severity] : 'var(--v-text-dim)'
  const closedLabel = !isActive ? (CLOSED_LABEL[alert.lifecycle_state] ?? 'Closed') : null

  return (
    <div
      className="flex items-start justify-between gap-4 px-5 py-4 transition-colors"
      style={{
        background: 'var(--v-surface)',
        border: '0.5px solid var(--v-border)',
        borderLeft: `2px solid ${accentColor}`,
        borderRadius: 'var(--v-radius)',
        opacity: isActive ? 1 : 0.6,
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--v-surface)')}
    >
      <div className="flex items-start gap-3 min-w-0 flex-1">
        {isActive && alert.severity === 'critical' && (
          <span
            className="w-2 h-2 rounded-full shrink-0 mt-1.5 animate-pulse"
            style={{ background: SEVERITY_COLOR.critical }}
          />
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <span className="text-xs font-mono" style={{ color: 'var(--v-text-dim)' }}>
              {formatRelativeTime(alert.created_at)}
            </span>
            <span className="text-xs font-medium" style={{ color: 'var(--v-text-muted)' }}>{barName}</span>
            {isActive ? (
              <>
                <Badge variant={SEVERITY_BADGE[alert.severity]}>{alert.severity}</Badge>
                {alert.alert_type === 'anomaly' && <Badge variant="violet">Anomaly</Badge>}
              </>
            ) : (
              <Badge variant="dim">{closedLabel}</Badge>
            )}
          </div>
          <p className="text-sm leading-snug" style={{ color: isActive ? 'var(--v-text)' : 'var(--v-text-muted)' }}>
            {alert.message}
          </p>
        </div>
      </div>

      <div className="shrink-0">
        {isActive && (
          <Button variant="secondary" onClick={() => onAcknowledge(alert.id, alert.version)} disabled={acknowledging}>
            Acknowledge
          </Button>
        )}
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const liveEventQuery = useLiveEvent()
  const eventId = liveEventQuery.data?.id ?? null
  const alertsQuery = useAlertsForEvent(eventId, { onlyActive: false })
  const acknowledgeMutation = useAcknowledgeAlert()
  const perms = usePermissions()

  const alerts = (alertsQuery.data?.items ?? []) as AlertRowResolved[]

  const [activeFilter, setActiveFilter] = useState<FilterKey>('all')
  const [showAnomalies, setShowAnomalies] = useState(true)

  const handleAcknowledge = useCallback(
    (id: string, version: number) => {
      acknowledgeMutation.mutate({ alert_id: id, version })
    },
    [acknowledgeMutation],
  )

  const acknowledgedIds = useMemo(
    () => new Set(alerts.filter((a) => a.acknowledged_at !== null).map((a) => a.id)),
    [alerts],
  )

  const totalCount = alerts.length
  const unackedCount = alerts.filter((a) => a.lifecycle_state === 'active').length
  const criticalActive = alerts.filter((a) => a.severity === 'critical' && a.lifecycle_state === 'active').length

  const filtered = alerts.filter((a) => {
    if (perms.canSeeAnomalies && a.alert_type === 'anomaly') return false
    if (activeFilter === 'all') return true
    if (activeFilter === 'acknowledged') return acknowledgedIds.has(a.id)
    return a.severity === activeFilter && a.lifecycle_state === 'active'
  })

  const anomalyAlerts = alerts.filter((a) => {
    if (a.alert_type !== 'anomaly') return false
    if (activeFilter === 'all') return true
    if (activeFilter === 'acknowledged') return acknowledgedIds.has(a.id)
    return a.severity === activeFilter && a.lifecycle_state === 'active'
  })

  const subtitle = liveEventQuery.data
    ? `${liveEventQuery.data.name} · Live`
    : 'No live event'

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Alerts"
          subtitle={subtitle}
          actions={
            unackedCount > 0 ? (
              <span className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full" style={{ background: 'rgba(255, 61, 113, 0.12)', color: 'var(--v-pink)' }}>
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--v-pink)' }} />
                {unackedCount} unacknowledged
              </span>
            ) : undefined
          }
        />
      </div>

      {!eventId && !liveEventQuery.isLoading ? (
        <EmptyState
          headline="No live event"
          body="Alerts are scoped to the currently live event. Activate an event from the Events page to see its alerts here."
        />
      ) : (
        <>
          {/* Summary tiles */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <MetricTile label="Total Alerts" value={String(totalCount)} />
            <MetricTile label="Unacknowledged" value={String(unackedCount)} accent="amber" />
            <MetricTile label="Critical Active" value={String(criticalActive)} accent="pink" />
          </div>

          {/* Filter pills */}
          <div className="flex items-center gap-2 flex-wrap mb-4">
            {FILTER_LABELS.map(({ key, label }) => (
              <FilterPill
                key={key}
                label={label}
                count={
                  key === 'all' ? totalCount :
                  key === 'critical' ? criticalActive :
                  key === 'warning' ? alerts.filter((a) => a.severity === 'warning' && a.lifecycle_state === 'active').length :
                  acknowledgedIds.size
                }
                isActive={activeFilter === key}
                onClick={() => setActiveFilter(key)}
              />
            ))}
          </div>

          {/* Alert list */}
          {alertsQuery.isLoading ? (
            <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
              <div className="inline-flex items-center gap-2">
                <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                Loading alerts…
              </div>
            </div>
          ) : alertsQuery.isError ? (
            <div className="py-8 text-center text-sm" style={{ color: 'var(--v-pink)' }}>
              Failed to load alerts.
            </div>
          ) : filtered.length === 0 && anomalyAlerts.length === 0 ? (
            <EmptyState headline="No alerts match this filter" body="Try a different filter, or check back once the event is underway." />
          ) : filtered.length === 0 ? null : (
            <div className="space-y-2 mb-6">
              {filtered.map((alert) => (
                <AlertListRow
                  key={alert.id}
                  alert={alert}
                  onAcknowledge={handleAcknowledge}
                  acknowledging={acknowledgeMutation.isPending}
                />
              ))}
            </div>
          )}

          {/* Anomaly Detection section (owner only) */}
          {perms.canSeeAnomalies && anomalyAlerts.length > 0 && (
            <section
              className="overflow-hidden"
              style={{
                background: 'var(--v-surface)',
                border: '0.5px solid var(--v-border)',
                borderLeft: '2px solid var(--v-violet)',
                borderRadius: 'var(--v-radius-lg)',
              }}
            >
              <button
                type="button"
                onClick={() => setShowAnomalies((v) => !v)}
                className="w-full flex items-center gap-2.5 px-5 py-4 text-left"
                style={{ borderBottom: showAnomalies ? '0.5px solid var(--v-border)' : 'none' }}
                aria-expanded={showAnomalies}
              >
                <h2 className="text-sm font-medium" style={{ color: 'var(--v-violet)' }}>Anomaly Detection</h2>
                <Badge variant="violet">Owner Only</Badge>
                <span className="ml-auto text-[10px] font-medium uppercase tracking-wide" style={{ color: 'var(--v-text-dim)' }}>
                  {anomalyAlerts.length} {anomalyAlerts.length === 1 ? 'item' : 'items'}
                </span>
                <span style={{ color: 'var(--v-text-dim)' }}>{showAnomalies ? '▾' : '▸'}</span>
              </button>
              {showAnomalies && (
                <div className="p-4 space-y-3">
                  {anomalyAlerts.map((alert) => {
                    const isActive = alert.lifecycle_state === 'active'
                    const barName = (alert.context_json?.bar_name as string) ?? 'Unknown bar'
                    return (
                      <div
                        key={alert.id}
                        className="px-4 py-4"
                        style={{
                          background: 'var(--v-surface-raised)',
                          border: '0.5px solid var(--v-border)',
                          borderRadius: 'var(--v-radius)',
                          opacity: isActive ? 1 : 0.6,
                        }}
                      >
                        <div className="flex items-start justify-between gap-4 mb-2">
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] font-mono" style={{ color: 'var(--v-text-dim)' }}>
                                {formatRelativeTime(alert.created_at)}
                              </span>
                              <span className="text-xs font-medium" style={{ color: 'var(--v-violet)' }}>{barName}</span>
                            </div>
                            <p className="text-sm font-medium" style={{ color: isActive ? 'var(--v-text)' : 'var(--v-text-muted)' }}>
                              {alert.message}
                            </p>
                          </div>
                          {isActive && (
                            <Button
                              variant="secondary"
                              onClick={() => handleAcknowledge(alert.id, alert.version)}
                              disabled={acknowledgeMutation.isPending}
                            >
                              Acknowledge
                            </Button>
                          )}
                        </div>
                        <div className="pt-2.5 mt-2.5" style={{ borderTop: '0.5px solid var(--v-border)' }}>
                          <p className="text-[10px] font-medium uppercase tracking-wide mb-1.5" style={{ color: 'var(--v-text-dim)' }}>
                            Possible Causes
                          </p>
                          <div className="flex flex-wrap gap-1.5">
                            {DEFAULT_CAUSES.map((cause) => (
                              <Badge key={cause} variant="violet">{cause}</Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
