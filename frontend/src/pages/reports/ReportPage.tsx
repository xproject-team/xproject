/**
 * ReportPage — post-event decision intelligence reports.
 *
 * Replaces the 546-line mock scaffold with real backend-wired data:
 *   - Portfolio Insights Strip (4 tiles from GET /reports/portfolio/kpis)
 *   - Past Reports list (cards from GET /reports)
 *   - Generate New Report action (POST /reports/generate)
 *
 * Intentionally DROPPED from the old mockup:
 *   - Blue "Current Event / In Progress" card — category error; Dashboard
 *     is the live surface, Reports is the archive.
 *   - "AI-Generated Narrative" accordion — the narrative engine is
 *     rule-based template filling, not LLM-generated. Showing the label
 *     "AI-Generated" would be a trust violation. Narrative lives inside
 *     individual reports at /reports/:id (see ReportDetailPage).
 *
 * Spec: docs/report-module-spec.md §3 + §8.1.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

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

function PortfolioStripTile({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 flex flex-col gap-1 shadow-sm">
      <p className="text-[11px] font-semibold text-[#718096] uppercase tracking-widest">
        {label}
      </p>
      <p className="text-2xl font-bold text-[#1A202C] leading-tight">{value}</p>
      {hint && <p className="text-xs text-[#A0AEC0]">{hint}</p>}
    </div>
  )
}

function PortfolioStrip({ kpis }: { kpis: PortfolioKpis | undefined }) {
  const isLoading = kpis === undefined
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <PortfolioStripTile
        label="Completed Events"
        value={isLoading ? '…' : String(kpis!.total_events_completed)}
        hint={
          kpis && kpis.total_events_completed === 0
            ? 'After your first event ends'
            : kpis && kpis.events_delta_vs_last_quarter !== 0
              ? `${kpis.events_delta_vs_last_quarter > 0 ? '+' : ''}${kpis.events_delta_vs_last_quarter} vs last quarter`
              : undefined
        }
      />
      <PortfolioStripTile
        label="Lifetime Revenue"
        value={isLoading ? '…' : fmtEur(kpis!.lifetime_revenue)}
        hint={kpis?.revenue_delta_pct_yoy !== null && kpis?.revenue_delta_pct_yoy !== undefined
          ? `${kpis.revenue_delta_pct_yoy > 0 ? '+' : ''}${kpis.revenue_delta_pct_yoy.toFixed(0)}% YoY`
          : undefined}
      />
      <PortfolioStripTile
        label="Avg / Event"
        value={isLoading ? '…' : fmtEur(kpis!.avg_event_revenue)}
      />
      <PortfolioStripTile
        label="Best Event"
        value={isLoading || !kpis!.best_event_name ? '—' : kpis!.best_event_name}
        hint={kpis?.best_event_revenue ? fmtEur(kpis.best_event_revenue) : undefined}
      />
    </div>
  )
}

// ─── Latest-version grouping ──────────────────────────────────────────────────
//
// The list endpoint (GET /reports) returns every version of every report,
// each with `version` but no `superseded_by` (that flag only exists on the
// single-report detail response). So "latest per event+language" has to be
// derived here: group by (event_id, language), keep the highest version as
// the visible row, and collapse the rest behind a "superseded" toggle.

interface ReportGroupData {
  latest: ReportSummary
  older: ReportSummary[]
}

function groupReportsByLatest(reports: ReportSummary[]): ReportGroupData[] {
  const groups = new Map<string, ReportGroupData>()
  const order: string[] = []
  for (const r of reports) {
    const key = `${r.event_id}::${r.language}`
    const existing = groups.get(key)
    if (!existing) {
      groups.set(key, { latest: r, older: [] })
      order.push(key)
    } else if (r.version > existing.latest.version) {
      existing.older.push(existing.latest)
      existing.latest = r
    } else {
      existing.older.push(r)
    }
  }
  return order.map((key) => groups.get(key)!)
}

// ─── Report Card (one per row in Past Reports list) ──────────────────────────

function StatusBadge({ status }: { status: ReportSummary['status'] }) {
  const config = {
    ready:      { bg: '#C6F6D5', text: '#22543D', label: 'Complete'   },
    generating: { bg: '#BEE3F8', text: '#2C5282', label: 'Generating' },
    pending:    { bg: '#E2E8F0', text: '#4A5568', label: 'Pending'    },
    failed:     { bg: '#FED7D7', text: '#742A2A', label: 'Failed'     },
  }[status]
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold"
      style={{ backgroundColor: config.bg, color: config.text }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: config.text }} />
      {config.label}
    </span>
  )
}

function ReportCard({ report, superseded = false }: { report: ReportSummary; superseded?: boolean }) {
  return (
    <Link
      to={`/reports/${report.id}`}
      className={`block bg-white border border-[#E2E8F0] rounded-xl p-5 hover:shadow-md hover:border-[#CBD5E0] transition-all ${
        superseded ? 'opacity-70' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        {/* Left: event info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <h3
              className="font-semibold truncate"
              style={{ color: superseded ? 'var(--v-text-muted)' : '#1A202C' }}
            >
              {report.event_name}
            </h3>
            <span className="text-[11px] text-[#A0AEC0] uppercase tracking-widest">
              {report.language}
            </span>
            {(report.version > 1 || superseded) && (
              <span className="text-[11px] px-1.5 rounded bg-[#EDF2F7] text-[#4A5568]">
                v{report.version}
              </span>
            )}
            {superseded && (
              <span
                className="text-[11px] px-1.5 rounded"
                style={{ color: 'var(--v-text-muted)', background: 'rgba(155, 163, 180, 0.12)' }}
              >
                Superseded
              </span>
            )}
          </div>
          <p className="text-xs" style={{ color: superseded ? 'var(--v-text-muted)' : '#718096' }}>
            Event: {fmtDate(report.event_started_at)} · Generated: {fmtDate(report.generated_at)}
          </p>

          {/* Quick metrics row — only if ready */}
          {report.status === 'ready' && (
            <div className="flex items-center gap-4 mt-3 text-xs text-[#4A5568]">
              {report.total_revenue && (
                <span>
                  💰 <b className="text-[#1A202C]">{fmtEur(report.total_revenue)}</b>
                </span>
              )}
              {report.top_bar_name && (
                <span>
                  🏆 <b className="text-[#1A202C]">{report.top_bar_name}</b>
                </span>
              )}
              {report.alerts_count !== null && report.alerts_count > 0 && (
                <span>
                  🚨 <b className="text-[#1A202C]">{report.alerts_count}</b> alert{report.alerts_count === 1 ? '' : 's'}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Right: status + arrow */}
        <div className="flex flex-col items-end gap-2 shrink-0">
          <StatusBadge status={report.status} />
          <span className="text-[#A0AEC0] text-lg">→</span>
        </div>
      </div>
    </Link>
  )
}

// ─── Report Group (latest version + collapsed superseded versions) ───────────

function ReportGroup({ group }: { group: ReportGroupData }) {
  const [expanded, setExpanded] = useState(false)
  const olderSorted = [...group.older].sort((a, b) => b.version - a.version)

  return (
    <div className="flex flex-col gap-2">
      <ReportCard report={group.latest} />
      {olderSorted.length > 0 && (
        <div className="pl-1">
          <button
            onClick={() => setExpanded((e) => !e)}
            className="text-xs hover:underline"
            style={{ color: 'var(--v-text-muted)' }}
          >
            {expanded ? '▾' : '▸'} {olderSorted.length} superseded version
            {olderSorted.length === 1 ? '' : 's'}
          </button>
          {expanded && (
            <div className="flex flex-col gap-2 mt-2">
              {olderSorted.map((r) => (
                <ReportCard key={r.id} report={r} superseded />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Empty state ─────────────────────────────────────────────────────────────

function EmptyReportsList() {
  return (
    <div className="bg-white border border-dashed border-[#CBD5E0] rounded-xl p-12 text-center">
      <p className="text-4xl mb-3">📊</p>
      <p className="text-[#4A5568] font-semibold mb-1">No reports yet</p>
      <p className="text-xs text-[#718096] max-w-sm mx-auto">
        Reports are generated automatically after an event ends. You can also trigger one
        on demand using the button above.
      </p>
    </div>
  )
}

// ─── Generate modal (minimal — picks event + language) ───────────────────────

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
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl">
        <h2 className="text-lg font-bold text-[#1A202C] mb-1">Generate New Report</h2>
        <p className="text-xs text-[#718096] mb-5">
          Choose a completed event and a language. The report will be generated immediately.
        </p>

        <label className="block text-xs font-semibold text-[#4A5568] mb-1 uppercase tracking-widest">
          Event
        </label>
        {eventsQuery.isLoading ? (
          <div className="px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm text-[#A0AEC0] mb-4">Loading events…</div>
        ) : eligibleEvents.length === 0 ? (
          <div className="px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm text-[#A0AEC0] mb-4">
            No completed events yet. Reports can only be generated after an event ends.
          </div>
        ) : (
          <select
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
            className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-sm mb-4 bg-white"
          >
            {eligibleEvents.length > 1 && <option value="">Choose an event…</option>}
            {eligibleEvents.map((ev) => (
              <option key={ev.id} value={ev.id}>
                {ev.name}
              </option>
            ))}
          </select>
        )}

        <label className="block text-xs font-semibold text-[#4A5568] mb-1 uppercase tracking-widest">
          Language
        </label>
        <div className="flex gap-2 mb-5">
          {(['it', 'en'] as const).map((lang) => (
            <button
              key={lang}
              onClick={() => setLanguage(lang)}
              className={`flex-1 py-2 text-sm rounded-lg border transition-colors ${
                language === lang
                  ? 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                  : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:bg-[#F7FAFC]'
              }`}
            >
              {lang === 'it' ? '🇮🇹 Italiano' : '🇬🇧 English'}
            </button>
          ))}
        </div>

        {generate.isError && (
          <div className="bg-[#FED7D7] text-[#742A2A] text-xs rounded-lg px-3 py-2 mb-4">
            Generation failed. Verify the event ID and that the event is completed.
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={generate.isPending}
            className="px-4 py-2 text-sm text-[#4A5568] hover:bg-[#F7FAFC] rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={handleGenerate}
            disabled={generate.isPending || !eventId.trim()}
            className="px-4 py-2 text-sm bg-[#1E5A8D] text-white rounded-lg hover:bg-[#17456D] disabled:opacity-50"
          >
            {generate.isPending ? 'Generating…' : 'Generate'}
          </button>
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
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">Event Reports</h1>
          <p className="text-sm text-[#718096] mt-1">
            Post-event intelligence — revenue, stock, alerts, and narrative recap.
          </p>
        </div>
        <button
          onClick={() => setShowGenerate(true)}
          className="bg-[#1E5A8D] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#17456D] shrink-0"
        >
          + Generate New Report
        </button>
      </div>

      {/* Portfolio Insights Strip */}
      <div className="mb-8">
        <PortfolioStrip kpis={kpis} />
      </div>

      {/* Past Reports list */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold text-[#718096] uppercase tracking-widest">
            Past Reports
          </h2>
          {reports && reports.length > 0 && (
            <span className="text-xs text-[#A0AEC0]">
              {reports.length} report{reports.length === 1 ? '' : 's'}
            </span>
          )}
        </div>

        {reportsLoading && (
          <div className="text-center py-12 text-sm text-[#A0AEC0]">Loading…</div>
        )}

        {reportsError && (
          <div className="bg-[#FED7D7] text-[#742A2A] text-sm rounded-xl p-4">
            Failed to load reports. Refresh to retry.
          </div>
        )}

        {reports && reports.length === 0 && <EmptyReportsList />}

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
