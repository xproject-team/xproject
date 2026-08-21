/**
 * ReportPage — post-event decision intelligence reports.
 *
 * Day 14: converted to the Vera dark design system (PageHeader,
 * MetricTile, Card, Badge, EmptyState, wizardForm inputs, established
 * modal treatment) — matching the other converted pages.
 *
 *   - Portfolio Insights Strip (4 tiles from GET /reports/portfolio/kpis)
 *   - Past Reports list (cards from GET /reports)
 *   - Generate New Report action (POST /reports/generate)
 *
 * Latest-version grouping prefers the newest READY version as the
 * visible card: a failed regenerate must never hide the good report
 * behind a "Failed" card (C5) — the failed attempt is still listed,
 * under the superseded/older toggle.
 *
 * Intentionally DROPPED from the old mockup (see git history):
 *   - Blue "Current Event / In Progress" card — category error; Dashboard
 *     is the live surface, Reports is the archive.
 *   - "AI-Generated Narrative" accordion — the narrative engine is
 *     rule-based template filling, not LLM-generated.
 *
 * Spec: docs/report-module-spec.md §3 + §8.1.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Badge, Button, Card, EmptyState, MetricTile, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label } from '@/design-system/wizardForm'
import {
  usePortfolioKpis,
  useReports,
  useGenerateReport,
  type PortfolioKpis,
  type ReportSummary,
  type ReportLanguage,
} from '@/features/reports/useReports'
import { useEvents } from '@/features/events/hooks'

// ─── Formatting helpers ──────────────────────────────────────────────────────

function fmtEur(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return `€${n.toLocaleString('it-IT', { maximumFractionDigits: 0 })}`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('it-IT', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

// ─── Portfolio Insights Strip (4 KPI tiles) ──────────────────────────────────

function PortfolioStrip({ kpis }: { kpis: PortfolioKpis | undefined }) {
  const isLoading = kpis === undefined
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <MetricTile
        label="Completed Events"
        value={isLoading ? '…' : String(kpis.total_events_completed)}
      >
        {kpis && kpis.total_events_completed === 0 && (
          <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
            After your first event ends
          </span>
        )}
      </MetricTile>
      <MetricTile
        label="Lifetime Revenue"
        value={isLoading ? '…' : fmtEur(kpis.lifetime_revenue)}
        accent="cyan"
      />
      <MetricTile label="Avg / Event" value={isLoading ? '…' : fmtEur(kpis.avg_event_revenue)} />
      <MetricTile
        label="Best Event"
        value={isLoading || !kpis.best_event_name ? '—' : kpis.best_event_name}
      >
        {kpis?.best_event_revenue != null && (
          <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
            {fmtEur(kpis.best_event_revenue)}
          </span>
        )}
      </MetricTile>
    </div>
  )
}

// ─── Latest-version grouping ──────────────────────────────────────────────────
//
// The list endpoint (GET /reports) returns every version of every report.
// Group by (event_id, language); the visible card is the newest READY
// version when one exists (a failed regenerate must not eclipse the good
// report — C5), otherwise the newest version whatever its status. The
// rest collapse behind the "older versions" toggle.

interface ReportGroupData {
  latest: ReportSummary
  older: ReportSummary[]
}

function groupReportsByLatest(reports: ReportSummary[]): ReportGroupData[] {
  const buckets = new Map<string, ReportSummary[]>()
  const order: string[] = []
  for (const r of reports) {
    const key = `${r.event_id}::${r.language}`
    const bucket = buckets.get(key)
    if (bucket) {
      bucket.push(r)
    } else {
      buckets.set(key, [r])
      order.push(key)
    }
  }
  return order.map((key) => {
    const bucket = [...buckets.get(key)!].sort((a, b) => b.version - a.version)
    const latest = bucket.find((r) => r.status === 'ready') ?? bucket[0]
    return { latest, older: bucket.filter((r) => r !== latest) }
  })
}

// ─── Report Card (one per row in Past Reports list) ──────────────────────────

const STATUS_BADGE: Record<ReportSummary['status'], { variant: BadgeVariant; label: string }> = {
  ready:      { variant: 'success', label: 'Complete'   },
  generating: { variant: 'info',    label: 'Generating' },
  pending:    { variant: 'neutral', label: 'Pending'    },
  failed:     { variant: 'danger',  label: 'Failed'     },
}

function ReportCard({ report, superseded = false }: { report: ReportSummary; superseded?: boolean }) {
  const statusCfg = STATUS_BADGE[report.status]
  return (
    <Link to={`/reports/${report.id}`} className={`block ${superseded ? 'opacity-70' : ''}`}>
      <Card className="transition-colors hover:bg-[var(--v-surface-raised)]">
        <div className="flex items-start justify-between gap-4">
          {/* Left: event info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <h3
                className="font-medium truncate"
                style={{ color: superseded ? 'var(--v-text-muted)' : 'var(--v-text)' }}
              >
                {report.event_name}
              </h3>
              <span
                className="text-[11px] uppercase tracking-widest"
                style={{ color: 'var(--v-text-dim)' }}
              >
                {report.language}
              </span>
              {(report.version > 1 || superseded) && (
                <Badge variant="neutral">v{report.version}</Badge>
              )}
              {superseded && <Badge variant="dim">Superseded</Badge>}
            </div>
            <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>
              Event: {fmtDate(report.event_started_at)} · Generated: {fmtDate(report.generated_at)}
            </p>

            {/* Quick metrics row — only if ready */}
            {report.status === 'ready' && (
              <div
                className="flex items-center gap-4 mt-3 text-xs"
                style={{ color: 'var(--v-text-muted)' }}
              >
                {report.total_revenue != null && (
                  <span>
                    Revenue{' '}
                    <b style={{ color: 'var(--v-text)' }}>{fmtEur(report.total_revenue)}</b>
                  </span>
                )}
                {report.top_bar_name && (
                  <span>
                    Top bar <b style={{ color: 'var(--v-text)' }}>{report.top_bar_name}</b>
                  </span>
                )}
                {report.alerts_count !== null && report.alerts_count > 0 && (
                  <span>
                    <b style={{ color: 'var(--v-text)' }}>{report.alerts_count}</b> alert
                    {report.alerts_count === 1 ? '' : 's'}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Right: status + arrow */}
          <div className="flex flex-col items-end gap-2 shrink-0">
            <Badge variant={statusCfg.variant}>{statusCfg.label}</Badge>
            <span className="text-lg" style={{ color: 'var(--v-text-dim)' }}>→</span>
          </div>
        </div>
      </Card>
    </Link>
  )
}

// ─── Report Group (visible version + collapsed older versions) ───────────────

function ReportGroup({ group }: { group: ReportGroupData }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="flex flex-col gap-2">
      <ReportCard report={group.latest} />
      {group.older.length > 0 && (
        <div className="pl-1">
          <button
            onClick={() => setExpanded((e) => !e)}
            className="text-xs hover:underline"
            style={{ color: 'var(--v-text-dim)' }}
          >
            {expanded ? '▾' : '▸'} {group.older.length} older version
            {group.older.length === 1 ? '' : 's'}
          </button>
          {expanded && (
            <div className="flex flex-col gap-2 mt-2">
              {group.older.map((r) => (
                <ReportCard key={r.id} report={r} superseded />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Generate modal (established dark modal treatment) ───────────────────────

function GenerateModal({
  open,
  onClose,
  onGenerated,
}: {
  open: boolean
  onClose: () => void
  onGenerated: (reportId: string) => void
}) {
  const [eventId, setEventId] = useState('')
  const [language, setLanguage] = useState<ReportLanguage>('it')
  const generate = useGenerateReport()
  const eventsQuery = useEvents()
  const allEvents = eventsQuery.data ?? []
  // Only completed events can have reports generated.
  const eligibleEvents = allEvents.filter((e) => e.status === 'completed')

  // Auto-select when there's a single eligible event and nothing chosen yet.
  if (open && !eventId && eligibleEvents.length === 1) {
    setEventId(eligibleEvents[0].id)
  }

  if (!open) return null

  const handleGenerate = async () => {
    if (!eventId.trim()) return
    try {
      const report = await generate.mutateAsync({ event_id: eventId.trim(), language })
      onGenerated(report.id)
      onClose()
    } catch {
      // Error state shown inline via generate.isError below
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div
        className="rounded-2xl max-w-md w-full p-6"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
      >
        <h2 className="text-lg font-medium mb-1" style={{ color: 'var(--v-text)' }}>
          Generate New Report
        </h2>
        <p className="text-xs mb-5" style={{ color: 'var(--v-text-muted)' }}>
          Choose a completed event and a language. The report will be generated immediately.
        </p>

        <div className="mb-4">
          <Label>Event</Label>
          {eventsQuery.isLoading ? (
            <p className="text-sm py-2" style={{ color: 'var(--v-text-dim)' }}>
              Loading events…
            </p>
          ) : eligibleEvents.length === 0 ? (
            <p className="text-sm py-2" style={{ color: 'var(--v-text-dim)' }}>
              No completed events yet. Reports can only be generated after an event ends.
            </p>
          ) : (
            <select
              className={inputCls}
              value={eventId}
              onChange={(e) => setEventId(e.target.value)}
            >
              {eligibleEvents.length > 1 && <option value="">Choose an event…</option>}
              {eligibleEvents.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="mb-5">
          <Label>Language</Label>
          <div className="flex gap-2">
            {(['it', 'en'] as const).map((lang) => (
              <Button
                key={lang}
                variant={language === lang ? 'primary' : 'secondary'}
                className="flex-1"
                onClick={() => setLanguage(lang)}
              >
                {lang === 'it' ? '🇮🇹 Italiano' : '🇬🇧 English'}
              </Button>
            ))}
          </div>
        </div>

        {generate.isError && (
          <p className="text-sm mb-4" style={{ color: 'var(--v-pink)' }}>
            Generation failed. Verify the event is completed, then try again.
          </p>
        )}

        <div className="flex gap-2 justify-end">
          <Button variant="ghost" onClick={onClose} disabled={generate.isPending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleGenerate}
            disabled={generate.isPending || !eventId.trim()}
          >
            {generate.isPending ? 'Generating…' : 'Generate'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ReportPage() {
  const navigate = useNavigate()
  const [showGenerate, setShowGenerate] = useState(false)

  const { data: kpis } = usePortfolioKpis()
  const { data: reports, isLoading: reportsLoading, isError: reportsError } = useReports({ limit: 50 })

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Event Reports"
          subtitle="Post-event intelligence — revenue, stock, alerts, and narrative recap."
          actions={
            <Button variant="primary" onClick={() => setShowGenerate(true)}>
              + Generate New Report
            </Button>
          }
        />
      </div>

      {/* Portfolio Insights Strip */}
      <div className="mb-8">
        <PortfolioStrip kpis={kpis} />
      </div>

      {/* Past Reports list */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="v-label">Past Reports</h2>
          {reports && reports.length > 0 && (
            <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
              {reports.length} report{reports.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        {reportsLoading && (
          <div className="text-center py-12 text-sm" style={{ color: 'var(--v-text-dim)' }}>
            Loading…
          </div>
        )}

        {reportsError && (
          <Card>
            <p className="text-sm" style={{ color: 'var(--v-pink)' }}>
              Failed to load reports. Refresh to retry.
            </p>
          </Card>
        )}

        {reports && reports.length === 0 && (
          <Card padded={false}>
            <EmptyState
              headline="No reports yet"
              body="Reports are generated automatically after an event ends. You can also trigger one on demand."
              action={
                <Button variant="secondary" onClick={() => setShowGenerate(true)}>
                  Generate New Report
                </Button>
              }
            />
          </Card>
        )}

        {reports && reports.length > 0 && (
          <div className="flex flex-col gap-3">
            {groupReportsByLatest(reports).map((g) => (
              <ReportGroup key={`${g.latest.event_id}::${g.latest.language}`} group={g} />
            ))}
          </div>
        )}
      </div>

      {/* Generate modal */}
      <GenerateModal
        open={showGenerate}
        onClose={() => setShowGenerate(false)}
        onGenerated={(reportId) => navigate(`/reports/${reportId}`)}
      />
    </div>
  )
}
