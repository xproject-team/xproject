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
 *
 * Day 7A restyle: converted from the legacy `@/shared/ui/{Badge,Card,
 * EmptyState}` trio to the Vera design system. Financial figures follow
 * the same semantic color rule as the revenue breakdown modal: retained/
 * matched/positive -> green, discrepancies/missing/negative -> pink,
 * neutral -> plain text.
 */
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Badge, Card, EmptyState, type BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
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

/** Decimal-as-string sign check — pure string inspection, no parseFloat.
 *  "0", "0.00", "-0.00" all read as zero. */
function qtySign(s: string): 'negative' | 'zero' | 'positive' {
  const n = s.trim()
  if (n.startsWith('-') && /[1-9]/.test(n)) return 'negative'
  if (/[1-9]/.test(n)) return 'positive'
  return 'zero'
}

/** Financial semantic color for a quantity string: matched(0) -> green,
 *  any discrepancy (nonzero) -> pink, per the revenue-breakdown convention. */
function qtyDiscrepancyColor(s: string): string {
  return qtySign(s) === 'zero' ? 'var(--v-green)' : 'var(--v-pink)'
}

/**
 * PosStatusPill — maps PosVarianceStatus values to the Badge component.
 * Color choice mirrors business priority: pink is "investigate today",
 * green is "all good", amber is "watch it", neutral is "no signal yet".
 */
function PosStatusPill({ status }: { status: string }) {
  const cfg: Record<string, { label: string; variant: BadgeVariant }> = {
    NO_POS_DATA:          { label: 'No POS data',  variant: 'neutral' },
    NEEDS_RECIPE:         { label: 'Needs recipe', variant: 'neutral' },
    OK_WITHIN_THRESHOLD:  { label: 'OK',            variant: 'success' },
    OVER_POUR_MINOR:      { label: 'Over-pour',     variant: 'warning' },
    OVER_POUR_MODERATE:   { label: 'Over-pour',     variant: 'danger' },
    OVER_POUR_MAJOR:      { label: 'Over-pour!',    variant: 'danger' },
    UNDER_SCAN_MINOR:     { label: 'Under-scan',    variant: 'warning' },
    UNDER_SCAN_MAJOR:     { label: 'Under-scan!',   variant: 'danger' },
  }
  const entry = cfg[status] ?? { label: status, variant: 'neutral' as BadgeVariant }
  return <Badge variant={entry.variant}>{entry.label}</Badge>
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

/** Map a backend flag to a Badge variant. Defensive default for unknown values. */
function flagColor(flag: DeliveryGapFlag): BadgeVariant {
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
  emphasis?: 'normal' | 'danger' | 'success' | 'warning'
}) {
  const valueColor =
    emphasis === 'danger'  ? 'var(--v-pink)'
    : emphasis === 'success' ? 'var(--v-green)'
    : emphasis === 'warning' ? 'var(--v-amber)'
    : 'var(--v-text)'
  return (
    <div className="v-card p-4 flex-1 min-w-[160px]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.06em] mb-1" style={{ color: 'var(--v-text-muted)' }}>
        {label}
      </p>
      <p className="text-2xl font-medium tabular-nums" style={{ color: valueColor }}>{value}</p>
    </div>
  )
}

function AtAGlanceSection({ report }: { report: ReconciliationReport }) {
  const { totals } = report.summary
  return (
    <section className="mb-6">
      <h2 className="text-xs font-semibold uppercase tracking-[0.06em] mb-3" style={{ color: 'var(--v-text-muted)' }}>
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

      {/* S6: POS-side rollup cards.  Render only when POS data exists. */}
      {!totals.missing_pos_data && (
        <div className="flex flex-wrap gap-3 mt-3">
          <StatCard
            label="POS variance: OK"
            value={totals.pos_ok_count}
            emphasis={totals.pos_ok_count > 0 ? 'success' : 'normal'}
          />
          <StatCard
            label="Over-pour flagged"
            value={totals.pos_over_pour_count}
            emphasis={totals.pos_over_pour_count > 0 ? 'danger' : 'normal'}
          />
          <StatCard
            label="Under-scan flagged"
            value={totals.pos_under_scan_count}
            emphasis={totals.pos_under_scan_count > 0 ? 'warning' : 'normal'}
          />
          <StatCard
            label="Pending recipes"
            value={totals.pos_pending_recipes_count}
            emphasis="normal"
          />
        </div>
      )}
      {/* S6: honest contextual messaging about POS state */}
      {totals.missing_pos_data ? (
        <p className="mt-2 text-[11px] italic" style={{ color: 'var(--v-text-dim)' }}>
          POS sales data not yet wired — sold-vs-arrived signal will appear
          when Slesh integration produces data for this event.
        </p>
      ) : totals.pos_pending_recipes_count > 0 && totals.pos_ok_count === 0 ? (
        <p className="mt-2 text-[11px] italic" style={{ color: 'var(--v-text-dim)' }}>
          POS data is being received but {totals.pos_pending_recipes_count}{' '}
          {totals.pos_pending_recipes_count === 1 ? 'row needs' : 'rows need'} a recipe
          to decompose menu sales into bottle-level variance.
        </p>
      ) : null}
    </section>
  )
}

// ─── Section 2: Delivery gaps (3 render branches) ──────────────────────────

function GapRow({ gap }: { gap: EventProductGap }) {
  if (!gap.flag) return null
  return (
    <div className="flex items-center gap-3 py-3" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
      <div className="w-[88px] flex-shrink-0">
        <Badge variant={flagColor(gap.flag)}>{flagLabel(gap.flag)}</Badge>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold truncate" style={{ color: 'var(--v-text)' }}>
          {gap.product_name}
        </p>
        <p className="text-xs tabular-nums" style={{ color: 'var(--v-text-muted)' }}>
          Dispatched: {fmtQty(gap.dispatched_qty)}
          {' · '}Arrived: {fmtQty(gap.total_arrived_at_event)}
          {' · '}Gap: <span style={{ color: 'var(--v-pink)' }}>{fmtQty(gap.delivery_gap)}</span>
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
        <h2 className="text-xs font-semibold uppercase tracking-[0.06em] mb-3" style={{ color: 'var(--v-text-muted)' }}>
          Delivery gaps
        </h2>
        <Card>
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden>⏸</span>
            <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>
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
        <h2 className="text-xs font-semibold uppercase tracking-[0.06em] mb-3" style={{ color: 'var(--v-text-muted)' }}>
          Delivery gaps
        </h2>
        <div className="rounded-[var(--v-radius)] p-4" style={{ background: 'rgba(61, 255, 163, 0.08)', border: '0.5px solid var(--v-green)' }}>
          <div className="flex items-center gap-3">
            <span className="text-2xl" aria-hidden>✅</span>
            <div>
              <p className="text-sm font-semibold" style={{ color: 'var(--v-green)' }}>All clear</p>
              <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>
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
      <h2 className="text-xs font-semibold uppercase tracking-[0.06em] mb-3" style={{ color: 'var(--v-text-muted)' }}>
        Delivery gaps
        <span className="ml-2 normal-case font-normal tracking-normal" style={{ color: 'var(--v-pink)' }}>
          ({event_level_gaps.length} found)
        </span>
      </h2>
      <Card padded={false}>
        <div className="px-4 py-3 rounded-t-[var(--v-radius)]" style={{ background: 'rgba(255, 61, 113, 0.08)', borderBottom: '0.5px solid var(--v-pink)' }}>
          <p className="text-sm font-semibold" style={{ color: 'var(--v-pink)' }}>
            ⚠ Warehouse dispatched stock that didn&apos;t fully arrive at bars
          </p>
          <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
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
      className={`flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.06em] transition-colors ${
        numeric ? 'justify-end' : ''
      }`}
      style={{ color: 'var(--v-text-muted)' }}
      onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-text)')}
      onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-muted)')}
    >
      {label}
      {sortCol === col && (
        <span aria-hidden style={{ color: 'var(--v-cyan)' }}>{sortDir === 'asc' ? '↑' : '↓'}</span>
      )}
    </button>
  )

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>
          Bar × product activity
        </h2>
        {uniqueBars.length > 1 && (
          <div className="flex items-center gap-2">
            <label
              htmlFor="filter-bar"
              className="text-xs"
              style={{ color: 'var(--v-text-muted)' }}
            >
              Filter:
            </label>
            <select
              id="filter-bar"
              value={filterBarId}
              onChange={(e) => setFilterBarId(e.target.value)}
              className="text-sm rounded-[var(--v-radius-sm)] px-2 py-1 focus:outline-none transition-colors"
              style={{ background: 'var(--v-bg-base)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}
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
            headline={report.rows.length === 0 ? 'No scanning activity yet' : 'No rows match'}
            body={
              report.rows.length === 0
                ? 'No scanning activity yet for this event.'
                : 'No rows match the current filter.'
            }
          />
        </Card>
      ) : (
        <div className="overflow-x-auto v-card">
          <table className="w-full text-sm">
            <thead style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
              <tr>
                <th className="text-left px-3 py-2"><SortHeader col="bar" label="Bar" /></th>
                <th className="text-left px-3 py-2"><SortHeader col="product" label="Product" /></th>
                <th className="text-right px-3 py-2"><SortHeader col="arrived" label="Arrived" numeric /></th>
                <th className="text-right px-3 py-2"><SortHeader col="consumed" label="Consumed" numeric /></th>
                <th className="text-right px-3 py-2"><SortHeader col="net" label="Net" numeric /></th>
                {/* S6: POS columns.  Always rendered; cells use "—" for no-data. */}
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>POS sold</th>
                <th className="text-right px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Variance</th>
                <th className="text-left  px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => (
                <tr
                  key={`${r.bar_id}:${r.product_id}`}
                  className="transition-colors"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-3 py-2" style={{ color: 'var(--v-text)' }}>{r.bar_name}</td>
                  <td className="px-3 py-2" style={{ color: 'var(--v-text)' }}>{r.product_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--v-text)' }}>{fmtQty(r.arrived_qty)}</td>
                  <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--v-text)' }}>{fmtQty(r.consumed_qty)}</td>
                  {/* Net going negative means more was consumed than arrived —
                      a genuine discrepancy, made unmistakable in pink. Zero/
                      positive is just remaining stock, plain text. */}
                  <td
                    className="px-3 py-2 text-right tabular-nums font-semibold"
                    style={{ color: qtySign(r.net_qty) === 'negative' ? 'var(--v-pink)' : 'var(--v-text)' }}
                  >
                    {fmtQty(r.net_qty)}
                  </td>
                  {/* S6: POS columns — render "—" when the field is null. */}
                  <td className="px-3 py-2 text-right tabular-nums" style={{ color: 'var(--v-text)' }}>
                    {r.consumed_via_pos_qty === null ? <span style={{ color: 'var(--v-text-dim)' }}>—</span> : fmtQty(r.consumed_via_pos_qty)}
                  </td>
                  {/* Variance sign made unmistakable: 0 = matched (green),
                      nonzero = discrepancy (pink), with an explicit +/- sign
                      so the direction is legible at a glance. */}
                  <td className="px-3 py-2 text-right tabular-nums font-semibold">
                    {r.pos_variance_qty === null ? (
                      <span style={{ color: 'var(--v-text-dim)' }}>—</span>
                    ) : (
                      <span style={{ color: qtyDiscrepancyColor(r.pos_variance_qty) }}>
                        {qtySign(r.pos_variance_qty) === 'positive' ? '+' : ''}
                        {fmtQty(r.pos_variance_qty)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-left">
                    <PosStatusPill status={r.pos_variance_status} />
                  </td>
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
          className="text-sm hover:underline mb-2 inline-block"
          style={{ color: 'var(--v-cyan)' }}
        >
          ← Back to event
        </Link>
        <h1 className="text-2xl font-medium leading-tight" style={{ color: 'var(--v-text)' }}>
          Reconciliation report
        </h1>
        <p className="text-sm mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
          {report.event_name}
          <span className="mx-1" style={{ color: 'var(--v-text-dim)' }}>·</span>
          {eventWindow}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>
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
        <p className="text-sm" style={{ color: 'var(--v-pink)' }}>Event ID missing from URL.</p>
      </div>
    )
  }

  if (query.isLoading) {
    return (
      <div className="max-w-5xl mx-auto p-6">
        <p className="text-sm" style={{ color: 'var(--v-text-muted)' }}>Loading reconciliation report…</p>
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
          className="text-sm hover:underline mb-4 inline-block"
          style={{ color: 'var(--v-cyan)' }}
        >
          ← Back to events
        </Link>
        <div className="rounded-[var(--v-radius)] p-4" style={{ background: 'rgba(255, 61, 113, 0.08)', border: '0.5px solid var(--v-pink)' }}>
          <p className="text-sm font-semibold mb-1" style={{ color: 'var(--v-pink)' }}>
            Couldn&apos;t load the report
          </p>
          <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>
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
