/**
 * EventReconciliationPage — Owner-facing post-event reconciliation viewer.
 *
 * Consumes useReconciliationReport (Phase 6.12.1) which consumes the
 * 6.11 backend endpoint. The page answers Omar's 4 Monday-morning
 * questions in five seconds:
 *
 *   1. Did the event finish cleanly?     → header + event_status
 *   2. Where did stock disappear?         → Section 2: delivery gaps
 *   3. What was the busiest bar/product?  → Section 3: sortable grid
 *   4. Anything that looks wrong?         → red-flagged gaps at the top
 *
 * Route: /events/:event_id/reconciliation (Phase 6.12.3)
 * Permission: canGenerateReport (Owner only)
 *
 * ─── Six Sundance-safety properties enforced at the page level ─────────
 *   1. Wrapper handles every error state before Content mounts — Content
 *      receives non-null data, no defensive null-checks scattered through
 *   2. Decimal-as-string preserved; no parseFloat anywhere in this file
 *   3. Always-rendered Section 2 (3 branches, same visual slot) means
 *      "all clear" gets the same weight as "gaps found" — reassurance
 *      is explicit, not buried in a muted footer
 *   4. Severity-mapped Badge colors mirror business priority
 *   5. Empty states are discrete render paths, never null-deref
 *   6. Standard semantic table — prints reasonably on A4 paper
 */
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge } from '@/shared/ui/Badge'
import { Card } from '@/shared/ui/Card'
import { EmptyState } from '@/shared/ui/EmptyState'
import {
  useReconciliationReport,
  type DeliveryGapFlag,
  type EventProductGap,
  type ReconciliationReport,
  type ReconciliationRow,
} from '@/features/events/useReconciliationReport'

// ─── Formatting helpers ────────────────────────────────────────────────────

/** Format a Decimal-as-string for display.
 *  Strips trailing zeros past the decimal: "4.00" → "4", "3.50" → "3.5".
 *  Never parses to float — pure string manipulation preserves precision. */
function fmtQty(s: string): string {
  if (!s.includes('.')) return s
  const [whole, frac] = s.split('.')
  const trimmed = frac.replace(/0+$/, '')
  return trimmed ? `${whole}.${trimmed}` : whole
}

/** Format an ISO date for display: "Apr 17, 2026 at 10:29" */
function fmtDateTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

/** Map a backend flag to a Badge color. Defensive default for unknown values. */
function flagColor(
  flag: DeliveryGapFlag,
): 'danger' | 'warning' | 'neutral' {
  switch (flag) {
    case 'DELIVERY_GAP_MAJOR':
      return 'danger'
    case 'DELIVERY_GAP_MODERATE':
      return 'warning'
    case 'DELIVERY_GAP_MINOR':
      return 'neutral'
  }
}

/** Human-readable flag label for the Badge text. */
function flagLabel(flag: DeliveryGapFlag): string {
  switch (flag) {
    case 'DELIVERY_GAP_MAJOR':
      return 'MAJOR'
    case 'DELIVERY_GAP_MODERATE':
      return 'MODERATE'
    case 'DELIVERY_GAP_MINOR':
      return 'MINOR'
  }
}

// ─── Section 1: At-a-glance stat cards ─────────────────────────────────────

function StatCard({
  label,
  value,
  emphasis = 'normal',
}: {
  label: string
  value: string | number
  emphasis?: 'normal' | 'danger'
}) {
  const valueColor =
    emphasis === 'danger' ? 'text-[#E53E3E]' : 'text-[#1A202C]'
  const borderColor =
    emphasis === 'danger' ? 'border-[#FEB2B2]' : 'border-[#E2E8F0]'
  return (
    <div
      className={`bg-white border ${borderColor} rounded-lg p-4 flex-1 min-w-[160px]`}
    >
      <p className="text-[11px] font-semibold uppercase tracking-widest text-[#718096] mb-1">
        {label}
      </p>
      <p className={`text-2xl font-bold ${valueColor} tabular-nums`}>{value}</p>
    </div>
  )
}

function AtAGlanceSection({ report }: { report: ReconciliationReport }) {
  const { totals } = report.summary
  return (
    <section className="mb-6">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-3">
        At a glance
      </h2>
      <div className="flex flex-wrap gap-3">
        <StatCard label="Active rows" value={totals.active_rows} />
        <StatCard label="Bottles arrived" value={fmtQty(totals.total_arrived)} />
        <StatCard
          label="Bottles consumed"
          value={fmtQty(totals.total_consumed)}
        />
        <StatCard
          label="Delivery gaps"
          value={totals.event_delivery_gap_count}
          emphasis={totals.event_delivery_gap_count > 0 ? 'danger' : 'normal'}
        />
      </div>
      {totals.missing_pos_data && (
        <p className="mt-2 text-[11px] italic text-[#A0AEC0]">
          POS sales data not yet wired — sold-vs-arrived signal will appear
          when Slesh integration is live.
        </p>
      )}
    </section>
  )
}

// ─── Section 2: Delivery gaps (3 render branches) ──────────────────────────

function GapRow({ gap }: { gap: EventProductGap }) {
  if (!gap.flag) return null
  return (
    <div className="flex items-center gap-3 py-3 border-b border-[#EDF2F7] last:border-b-0">
      <div className="w-[88px] flex-shrink-0">
        <Badge label={flagLabel(gap.flag)} color={flagColor(gap.flag)} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-[#1A202C] truncate">
          {gap.product_name}
        </p>
        <p className="text-xs text-[#4A5568] tabular-nums">
          Dispatched: {fmtQty(gap.dispatched_qty)}
          {' · '}Arrived: {fmtQty(gap.total_arrived_at_event)}
          {' · '}Gap: {fmtQty(gap.delivery_gap)}
          {gap.gap_pct !== null && ` (${gap.gap_pct.toFixed(1)}%)`}
        </p>
      </div>
    </div>
  )
}

function DeliveryGapsSection({ report }: { report: ReconciliationReport }) {
  const { event_level_gaps } = report.summary

  // Branch 1: event never started → ⏸ pending
  if (report.event_started_at === null) {
    return (
      <section className="mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-3">
          Delivery gaps
        </h2>
        <Card className="bg-[#F7FAFC]">
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden>⏸</span>
            <p className="text-sm text-[#4A5568]">
              Reconciliation will populate after this event goes live.
            </p>
          </div>
        </Card>
      </section>
    )
  }

  // Branch 2: started but no gaps → ✅ all clear
  if (event_level_gaps.length === 0) {
    return (
      <section className="mb-6">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-3">
          Delivery gaps
        </h2>
        <div className="bg-[#D1FAE5] border border-[#10B981] rounded-lg p-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden>✅</span>
            <div>
              <p className="text-sm font-semibold text-[#065F46]">All clear</p>
              <p className="text-xs text-[#047857]">
                No delivery gaps detected.{' '}
                {fmtQty(report.summary.totals.total_arrived)} bottles arrived,
                all accounted for in the warehouse-to-bar transfer.
              </p>
            </div>
          </div>
        </div>
      </section>
    )
  }

  // Branch 3: gaps exist → ⚠ alarm card with list (sorted MAJOR → MINOR
  // server-side; we just render in order)
  return (
    <section className="mb-6">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568] mb-3">
        Delivery gaps
        <span className="ml-2 text-[#E53E3E] normal-case font-normal tracking-normal">
          ({event_level_gaps.length} found)
        </span>
      </h2>
      <Card className="!p-0">
        <div className="px-4 py-3 bg-[#FED7D7] border-b border-[#FEB2B2] rounded-t-lg">
          <p className="text-sm font-semibold text-[#742A2A]">
            ⚠ Warehouse dispatched stock that didn&apos;t fully arrive at bars
          </p>
          <p className="text-xs text-[#742A2A] mt-0.5 opacity-90">
            Sorted by severity. MAJOR means dispatched but no arrivals
            scanned — review urgent.
          </p>
        </div>
        <div className="px-4">
          {event_level_gaps.map((gap) => (
            <GapRow key={gap.product_id} gap={gap} />
          ))}
        </div>
      </Card>
    </section>
  )
}

// ─── Section 3: Bar × product grid (filter + sort) ─────────────────────────

type SortColumn = 'bar' | 'product' | 'arrived' | 'consumed' | 'net'
type SortDir = 'asc' | 'desc'

/** Numeric-aware comparator for Decimal-as-string fields.
 *  Sorts by numeric value WITHOUT parseFloat (preserves precision contract).
 *  Compares whole/fractional parts separately as numbers. */
function compareQty(a: string, b: string): number {
  const [aw = '0', af = ''] = a.split('.')
  const [bw = '0', bf = ''] = b.split('.')
  const wholeCmp = parseInt(aw, 10) - parseInt(bw, 10)
  if (wholeCmp !== 0) return wholeCmp
  // pad fractional parts so "5" vs "50" compares like decimals
  const maxLen = Math.max(af.length, bf.length)
  const ap = af.padEnd(maxLen, '0')
  const bp = bf.padEnd(maxLen, '0')
  return parseInt(ap || '0', 10) - parseInt(bp || '0', 10)
}

function BarProductGrid({ report }: { report: ReconciliationReport }) {
  const [filterBarId, setFilterBarId] = useState<string>('all')
  const [sortCol, setSortCol] = useState<SortColumn>('bar')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const uniqueBars = useMemo(() => {
    const seen = new Map<string, string>()
    for (const r of report.rows) seen.set(r.bar_id, r.bar_name)
    return [...seen.entries()].map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [report.rows])

  const visibleRows = useMemo(() => {
    let rows: ReconciliationRow[] = report.rows
    if (filterBarId !== 'all') {
      rows = rows.filter((r) => r.bar_id === filterBarId)
    }
    const sorted = [...rows].sort((a, b) => {
      let cmp = 0
      switch (sortCol) {
        case 'bar':      cmp = a.bar_name.localeCompare(b.bar_name); break
        case 'product':  cmp = a.product_name.localeCompare(b.product_name); break
        case 'arrived':  cmp = compareQty(a.arrived_qty, b.arrived_qty); break
        case 'consumed': cmp = compareQty(a.consumed_qty, b.consumed_qty); break
        case 'net':      cmp = compareQty(a.net_qty, b.net_qty); break
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [report.rows, filterBarId, sortCol, sortDir])

  const toggleSort = (col: SortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'bar' || col === 'product' ? 'asc' : 'desc')
    }
  }

  const SortHeader = ({
    col,
    label,
    numeric = false,
  }: {
    col: SortColumn
    label: string
    numeric?: boolean
  }) => (
    <button
      type="button"
      onClick={() => toggleSort(col)}
      className={`flex items-center gap-1 text-[11px] font-semibold uppercase tracking-widest text-[#4A5568] hover:text-[#1A202C] ${
        numeric ? 'justify-end' : ''
      }`}
    >
      {label}
      {sortCol === col && (
        <span aria-hidden>{sortDir === 'asc' ? '↑' : '↓'}</span>
      )}
    </button>
  )

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[#4A5568]">
          Bar × product activity
        </h2>
        {uniqueBars.length > 1 && (
          <div className="flex items-center gap-2">
            <label
              htmlFor="filter-bar"
              className="text-xs text-[#718096]"
            >
              Filter:
            </label>
            <select
              id="filter-bar"
              value={filterBarId}
              onChange={(e) => setFilterBarId(e.target.value)}
              className="text-sm border border-[#E2E8F0] rounded px-2 py-1
                         focus:outline-none focus:border-[#1E5A8D]"
            >
              <option value="all">All bars</option>
              {uniqueBars.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {visibleRows.length === 0 ? (
        <Card>
          <EmptyState
            message={
              report.rows.length === 0
                ? 'No scanning activity yet for this event.'
                : 'No rows match the current filter.'
            }
          />
        </Card>
      ) : (
        <div className="bg-white border border-[#E2E8F0] rounded-lg overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[#F7FAFC] border-b border-[#E2E8F0]">
              <tr>
                <th className="text-left px-3 py-2"><SortHeader col="bar" label="Bar" /></th>
                <th className="text-left px-3 py-2"><SortHeader col="product" label="Product" /></th>
                <th className="text-right px-3 py-2"><SortHeader col="arrived" label="Arrived" numeric /></th>
                <th className="text-right px-3 py-2"><SortHeader col="consumed" label="Consumed" numeric /></th>
                <th className="text-right px-3 py-2"><SortHeader col="net" label="Net" numeric /></th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => (
                <tr
                  key={`${r.bar_id}:${r.product_id}`}
                  className="border-b border-[#EDF2F7] last:border-b-0"
                >
                  <td className="px-3 py-2 text-[#1A202C]">{r.bar_name}</td>
                  <td className="px-3 py-2 text-[#1A202C]">{r.product_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#1A202C]">{fmtQty(r.arrived_qty)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#1A202C]">{fmtQty(r.consumed_qty)}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-semibold text-[#1A202C]">{fmtQty(r.net_qty)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ─── Content (receives non-null data) ──────────────────────────────────────

function ReconciliationContent({ report }: { report: ReconciliationReport }) {
  const eventWindow =
    report.event_started_at === null
      ? 'Not yet started'
      : report.event_ended_at === null
        ? `${fmtDateTime(report.event_started_at)} → ongoing`
        : `${fmtDateTime(report.event_started_at)} → ${fmtDateTime(report.event_ended_at)}`

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6">
      <header className="mb-6">
        <Link
          to={`/events/${report.event_id}`}
          className="text-sm text-[#1E5A8D] hover:underline mb-2 inline-block"
        >
          ← Back to event
        </Link>
        <h1 className="text-2xl font-bold text-[#1A202C] leading-tight">
          Reconciliation report
        </h1>
        <p className="text-sm text-[#718096] mt-0.5">
          {report.event_name}
          <span className="mx-1 text-[#CBD5E0]">·</span>
          {eventWindow}
        </p>
        <p className="text-[11px] text-[#A0AEC0] mt-0.5">
          Generated {fmtDateTime(report.generated_at)}
        </p>
      </header>

      <AtAGlanceSection report={report} />
      <DeliveryGapsSection report={report} />
      <BarProductGrid report={report} />
    </div>
  )
}

// ─── Page wrapper (handles loading / error / not-found) ────────────────────

export function EventReconciliationPage() {
  const { event_id } = useParams<{ event_id: string }>()
  const query = useReconciliationReport(event_id)

  if (!event_id) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <p className="text-sm text-[#E53E3E]">Event ID missing from URL.</p>
      </div>
    )
  }

  if (query.isLoading) {
    return (
      <div className="max-w-5xl mx-auto p-6">
        <p className="text-sm text-[#718096]">Loading reconciliation report…</p>
      </div>
    )
  }

  if (query.isError || !query.data) {
    const isForbidden = query.error?.response?.status === 403
    const isNotFound = query.error?.response?.status === 404
    return (
      <div className="max-w-2xl mx-auto p-6">
        <Link
          to="/events"
          className="text-sm text-[#1E5A8D] hover:underline mb-4 inline-block"
        >
          ← Back to events
        </Link>
        <div className="bg-[#FEE2E2] border border-[#EF4444] rounded-lg p-4">
          <p className="text-sm font-semibold text-[#991B1B] mb-1">
            Couldn&apos;t load the report
          </p>
          <p className="text-xs text-[#991B1B] opacity-90">
            {isForbidden
              ? 'You don\'t have permission to view this report.'
              : isNotFound
                ? 'Event not found.'
                : 'Something went wrong. Try refreshing.'}
          </p>
        </div>
      </div>
    )
  }

  return <ReconciliationContent report={query.data} />
}
