import { useState, useCallback } from 'react'
import { formatRelativeTime } from '@/lib/utils'
import { useNavigate } from 'react-router-dom'
import { usePermissions } from '@/features/auth/usePermissions'
import { useLiveEvent } from '@/features/dashboard/hooks'
import { useAlertsForEvent, useAcknowledgeAlert } from '@/features/alerts/useAlerts'
import type { AlertRow } from '@/features/alerts/useAlerts'
import type { Alert, AlertSeverity } from '@/lib/mockData'

// Local widened type — adds the _version field that the adapter populates
// from AlertRow.version. We need this for optimistic-locking on acknowledge.
// Not added to the shared mockData Alert type to avoid surface area in the
// legacy mock layer.
type AlertWithVersion = Alert & { _version: number }

// ─── Style maps ───────────────────────────────────────────────────────────────

const SEVERITY_CFG: Record<AlertSeverity, {
  badge: string
  borderL: string
  bg: string
  dot: string
}> = {
  critical: {
    badge:   'bg-red-100 text-[#E53E3E] border border-red-200',
    borderL: 'border-l-[#E53E3E]',
    bg:      'bg-red-50/30',
    dot:     'bg-[#E53E3E]',
  },
  warning: {
    badge:   'bg-yellow-100 text-[#D69E2E] border border-yellow-200',
    borderL: 'border-l-[#D69E2E]',
    bg:      'bg-yellow-50/30',
    dot:     'bg-[#D69E2E]',
  },
  anomaly: {
    badge:   'bg-orange-100 text-[#E67E22] border border-orange-200',
    borderL: 'border-l-[#E67E22]',
    bg:      'bg-orange-50/30',
    dot:     'bg-[#E67E22]',
  },
}

// ─── Possible causes map for anomaly alerts ───────────────────────────────────

const ANOMALY_CAUSES: Record<string, string[]> = {
  'alrt-3':  ['Unreported promotions', 'Miscounted opening stock', 'Staff consumption'],
  'alrt-7':  ['Pricing discrepancy', 'POS sync delay', 'Promotional discount not logged'],
  'alrt-10': ['VIP guest spike', 'Unlogged bottle service', 'Pouring over-measure'],
}
const DEFAULT_CAUSES = ['Unusual demand pattern', 'Possible miscounting', 'Staff or promotional factor']

// ─── Filter types ─────────────────────────────────────────────────────────────

type FilterKey = 'all' | AlertSeverity | 'acknowledged'

const FILTER_LABELS: { key: FilterKey; label: string }[] = [
  { key: 'all',          label: 'All' },
  { key: 'critical',     label: 'Critical' },
  { key: 'warning',      label: 'Warning' },
  { key: 'anomaly',      label: 'Anomaly' },
  { key: 'acknowledged', label: 'Acknowledged' },
]

// ─── Alert card ───────────────────────────────────────────────────────────────

function AlertCard({
  alert,
  acked,
  onAcknowledge,
}: {
  alert: AlertWithVersion
  acked: boolean
  onAcknowledge: (id: string, version: number) => void
}) {
  const navigate = useNavigate()
  const cfg = SEVERITY_CFG[alert.severity]

  return (
    <div
      className={[
        'border border-[#E2E8F0] border-l-4 rounded-xl px-5 py-4 shadow-sm flex items-start justify-between gap-4 transition-all',
        cfg.borderL,
        acked ? 'bg-[#F7FAFC] opacity-60' : cfg.bg + ' bg-white',
      ].join(' ')}
    >
      {/* Left content */}
      <div className="flex items-start gap-4 min-w-0 flex-1">
        {/* Severity dot */}
        <div className={`w-2.5 h-2.5 rounded-full shrink-0 mt-1.5 ${cfg.dot} ${!acked && alert.severity === 'critical' ? 'animate-pulse' : ''}`} />

        <div className="min-w-0">
          {/* Top row: timestamp + bar name + severity badge */}
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs font-bold font-mono text-[#1A202C]">{formatRelativeTime(alert.created_at)}</span>
            <button
              onClick={() => navigate('/dashboard')}
              className={`text-xs font-semibold hover:underline ${
                alert.severity === 'critical' ? 'text-[#E53E3E]' :
                alert.severity === 'warning'  ? 'text-[#D69E2E]' :
                'text-[#E67E22]'
              }`}
            >
              {alert.bar_name}
            </button>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${cfg.badge}`}>
              {alert.severity}
            </span>
            {alert.alert_type === 'anomaly' && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-orange-50 text-[#E67E22] border border-orange-200 uppercase">
                Anomaly
              </span>
            )}
          </div>

          {/* Message */}
          <p className={`text-sm leading-snug ${acked ? 'text-[#718096]' : 'text-[#1A202C]'}`}>
            {alert.message}
          </p>
        </div>
      </div>

      {/* Right: acknowledge */}
      <div className="shrink-0 flex flex-col items-end gap-1.5 mt-0.5">
        {!acked ? (
          <button
            onClick={() => onAcknowledge(alert.id, alert._version)}
            className="text-xs font-semibold text-[#4A5568] border border-[#E2E8F0] bg-white hover:bg-[#EDF2F7] px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap"
          >
            Acknowledge
          </button>
        ) : (
          <span className="text-[11px] text-[#718096] italic">Acknowledged</span>
        )}
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const liveEventQuery = useLiveEvent()
  const eventId = liveEventQuery.data?.id ?? null
  const alertsQuery = useAlertsForEvent(eventId, { onlyActive: false })
  const acknowledgeMutation = useAcknowledgeAlert()
  // Adapter: map real AlertRow[] -> legacy Alert shape consumed by the existing
  // render logic. Drops no data; merely derives bar_name + is_acknowledged +
  // narrows severity for display consistency with the legacy mock type.
  const alertsSource = (alertsQuery.data?.items ?? []).map((row: AlertRow) => ({
    id:              row.id,
    event_id:        row.event_id,
    bar_id:          row.bar_id,
    bar_name:        (row.context_json?.bar_name as string) ?? 'Unknown bar',
    severity:        (row.severity === 'info' ? 'warning' : row.severity) as 'critical' | 'warning' | 'anomaly',
    alert_type:      row.alert_type,
    message:         row.message,
    created_at:      row.created_at,
    is_acknowledged: row.acknowledged_at !== null,
    _version:        row.version,
  }))
  const perms = usePermissions()

  const acknowledged = new Set(alertsSource.filter((a) => a.is_acknowledged).map((a) => a.id))
  const [activeFilter, setActiveFilter] = useState<FilterKey>('all')

  const handleAcknowledge = useCallback(
    (id: string, version: number) => {
      // Fires the real PATCH /alerts/{id}/acknowledge mutation.
      // version is required for optimistic locking — backend rejects stale acks.
      // The 'acknowledged' Set is derived from alertsSource, which is refetched
      // on mutation success — no local state needed.
      acknowledgeMutation.mutate({ alert_id: id, version })
    },
    [acknowledgeMutation],
  )

  // ── Derived counts ─────────────────────────────────────────────────────────
  const totalCount        = alertsSource.length
  const unackedCount      = alertsSource.filter((a) => !acknowledged.has(a.id)).length
  const criticalActive    = alertsSource.filter((a) => a.severity === 'critical' && !acknowledged.has(a.id)).length

  // ── Filtered list ──────────────────────────────────────────────────────────
  const filtered = alertsSource.filter((a) => {
    if (activeFilter === 'all')          return true
    if (activeFilter === 'acknowledged') return acknowledged.has(a.id)
    return a.severity === activeFilter && !acknowledged.has(a.id)
  })

  // ── Anomaly alerts (owner only) ────────────────────────────────────────────
  const anomalyAlerts = alertsSource.filter((a) => a.alert_type === 'anomaly')

  return (
    <div className="p-6 max-w-5xl mx-auto">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-6 mb-6 flex-wrap">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-bold text-[#1A202C]">Alert Center</h1>
            {unackedCount > 0 && (
              <span className="flex items-center gap-1.5 text-xs font-bold bg-red-100 text-[#E53E3E] border border-red-200 px-2.5 py-1 rounded-full">
                <span className="w-1.5 h-1.5 rounded-full bg-[#E53E3E] animate-pulse" />
                {unackedCount} unacknowledged
              </span>
            )}
          </div>
          <p className="text-sm text-[#4A5568]">Sundance 2026 · Live</p>
        </div>

        {/* ── Stat cards ──────────────────────────────────────────────── */}
        <div className="flex items-stretch gap-3 flex-wrap">
          {[
            { label: 'Total Alerts',      value: totalCount,     color: 'text-[#1A202C]' },
            { label: 'Unacknowledged',    value: unackedCount,   color: 'text-[#D69E2E]' },
            { label: 'Critical Active',   value: criticalActive, color: 'text-[#E53E3E]' },
          ].map(({ label, value, color }) => (
            <div
              key={label}
              className="bg-white border border-[#E2E8F0] rounded-xl px-4 py-3 shadow-sm text-center min-w-[100px]"
            >
              <p className={`text-2xl font-bold leading-none ${color}`}>{value}</p>
              <p className="text-[10px] font-semibold text-[#4A5568] uppercase tracking-wide mt-1">{label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Filter buttons ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap mb-5">
        {FILTER_LABELS.map(({ key, label }) => {
          const active = activeFilter === key
          return (
            <button
              key={key}
              onClick={() => setActiveFilter(key)}
              className={[
                'text-xs font-semibold px-3.5 py-1.5 rounded-full border transition-colors',
                active
                  ? key === 'critical'
                    ? 'bg-red-100 text-[#E53E3E] border-red-200'
                    : key === 'warning'
                    ? 'bg-yellow-100 text-[#D69E2E] border-yellow-200'
                    : key === 'anomaly'
                    ? 'bg-orange-100 text-[#E67E22] border-orange-200'
                    : key === 'acknowledged'
                    ? 'bg-gray-100 text-[#718096] border-gray-200'
                    : 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                  : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:bg-[#F7FAFC]',
              ].join(' ')}
            >
              {label}
              {key === 'critical' && criticalActive > 0 && (
                <span className="ml-1.5 bg-[#E53E3E] text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full">
                  {criticalActive}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Alert list ──────────────────────────────────────────────────── */}
      {filtered.length === 0 ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl px-6 py-10 text-center shadow-sm">
          <p className="text-sm font-medium text-[#4A5568]">No alerts match this filter.</p>
        </div>
      ) : (
        <div className="space-y-2.5 mb-8">
          {filtered.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              acked={acknowledged.has(alert.id)}
              onAcknowledge={handleAcknowledge}
            />
          ))}
        </div>
      )}

      {/* ── Anomaly Detection section (owner only) ───────────────────── */}
      {perms.canSeeAnomalies && anomalyAlerts.length > 0 && (
        <section className="border-l-4 border-l-[#E67E22] bg-orange-50/40 border border-orange-200 rounded-xl overflow-hidden shadow-sm">
          <div className="px-5 py-4 border-b border-orange-200 flex items-center gap-2.5">
            <svg className="w-4 h-4 text-[#E67E22] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <h2 className="text-sm font-bold text-[#E67E22]">Anomaly Detection</h2>
            <span className="text-[10px] font-bold bg-orange-100 text-[#E67E22] border border-orange-200 px-2 py-0.5 rounded-full uppercase tracking-wide">
              Owner Only
            </span>
          </div>

          <div className="p-4 space-y-3">
            {anomalyAlerts.map((alert) => {
              const causes = ANOMALY_CAUSES[alert.id] ?? DEFAULT_CAUSES
              const acked  = acknowledged.has(alert.id)
              return (
                <div
                  key={alert.id}
                  className={[
                    'bg-white border border-orange-200 rounded-xl px-4 py-4',
                    acked ? 'opacity-55' : '',
                  ].join(' ')}
                >
                  <div className="flex items-start justify-between gap-4 mb-2">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-bold font-mono text-[#E67E22]">{formatRelativeTime(alert.created_at)}</span>
                        <span className="text-xs font-semibold text-[#E67E22]">{alert.bar_name}</span>
                      </div>
                      <p className={`text-sm font-medium ${acked ? 'text-[#718096]' : 'text-[#1A202C]'}`}>
                        {alert.message}
                      </p>
                    </div>
                    {!acked && (
                      <button
                        onClick={() => handleAcknowledge(alert.id, alert._version)}
                        className="text-xs font-semibold text-[#4A5568] border border-[#E2E8F0] bg-white hover:bg-[#EDF2F7] px-3 py-1.5 rounded-lg transition-colors whitespace-nowrap shrink-0"
                      >
                        Acknowledge
                      </button>
                    )}
                  </div>
                  <div className="border-t border-orange-100 pt-2.5 mt-2.5">
                    <p className="text-[10px] font-bold text-[#E67E22] uppercase tracking-wide mb-1.5">
                      Possible Causes
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {causes.map((cause: string) => (
                        <span
                          key={cause}
                          className="text-[11px] bg-orange-100 text-[#E67E22] border border-orange-200 px-2 py-0.5 rounded-full"
                        >
                          {cause}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

    </div>
  )
}
