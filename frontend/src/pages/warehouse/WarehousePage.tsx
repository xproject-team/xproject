/**
 * WarehousePage — event storage view, LIVE event only.
 *
 * Design-system conversion (Day 12 Phase 3): same data/behavior as
 * before (useLiveEvent, useEventWarehouseSummary, useActivityFeed,
 * UploadInvoiceModal untouched) — UI-only restyle onto the dark design
 * system used by Events/Bars/Catalog/Inventory. No hook, type, or
 * backend change.
 *
 * Table note: this page has never fetched invoice-level data (supplier/
 * date/status) — useEventWarehouseSummary returns a PER-PRODUCT rollup
 * (invoiced/dispatched/remaining per item), which is what the table
 * below shows, restyled. Wiring up a real invoice list would mean
 * calling useInvoices, one of the eight hooks explicitly left alone for
 * this pass — that's a scope decision, not made here.
 *
 * Locks onto the tenant's single LIVE event (no picker). The whole
 * point of the warehouse view during operations is to monitor THE
 * event that's happening now; historical browsing is out of scope
 * for Sundance 1.
 *
 * KPIs: TOTAL ITEMS / TOTAL QUANTITY / ACTIVE ALLOCATIONS / TOTAL VALUE
 * Removed forever from this page: '+ New Delivery', AT RISK,
 * PENDING REVIEWS — none of those exist in the post-Phase-2 model.
 *
 * The legacy scan / invoice / pending-review pages at /warehouse/scan
 * and /warehouse/pending-review remain reachable by URL but no UI
 * leads there. Demolition deferred post-Sundance.
 *
 * Old scan-based source preserved as WarehousePage.tsx.scan-bak.
 */
import { useState } from 'react'

import { useLiveEvent } from '@/features/dashboard/hooks'
import { UploadInvoiceModal } from '@/features/warehouse/invoice_upload'
import { useEventWarehouseSummary } from '@/features/warehouse/useWarehouse'
import {
  useActivityFeed,
} from '@/features/event_storage/hooks'
import type {
  ActivityFeedRow,
} from '@/features/event_storage/types'
import { Badge, Button, EmptyState, MetricTile, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls } from '@/design-system/wizardForm'

const EUR = new Intl.NumberFormat('it-IT', {
  style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
})

function fmtEur(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return EUR.format(n)
}

function fmtQty(value: string): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return value
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function fmtTimeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  const now = Date.now()
  const secs = Math.floor((now - then) / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

type RemainingStatus = 'healthy' | 'low' | 'critical'

function remainingStatus(rem: number): RemainingStatus {
  if (rem < 0) return 'critical'
  if (rem < 5) return 'low'
  return 'healthy'
}

const REMAINING_BADGE: Record<RemainingStatus, BadgeVariant> = {
  healthy: 'success',
  low: 'warning',
  critical: 'danger',
}
const REMAINING_LABEL: Record<RemainingStatus, string> = {
  healthy: 'Healthy',
  low: 'Low',
  critical: 'Over-dispatched',
}

export default function WarehousePage() {
  // Phase invoice-upload (Jun 29 2026): modal for dropping fattura PDFs.
  // MUST be declared above any early-return guard or React's
  // Rules-of-Hooks gets violated when state transitions liveEvent
  // from null to non-null between renders.
  const [invoiceModalOpen, setInvoiceModalOpen] = useState(false)

  const liveEventQ = useLiveEvent()
  // T9/T11 — per-event invoiced summary. Lists every product Omar has
  // recorded an invoice for, scoped to THIS event. Falls back to an
  // empty card when no live event is set.
  const eventSummaryQ = useEventWarehouseSummary(liveEventQ.data?.id)
  const eventId = liveEventQ.data?.id

  const activityQ = useActivityFeed(eventId, 30)

  const eventSummary = eventSummaryQ.data
  const activity = activityQ.data ?? []

  const [search, setSearch] = useState('')

  const visibleRows = (() => {
    if (!eventSummary) return []
    const q = search.trim().toLowerCase()
    if (q === '') return eventSummary.rows
    return eventSummary.rows.filter(
      (r) =>
        r.product_name.toLowerCase().includes(q) ||
        (r.category ?? '').toLowerCase().includes(q),
    )
  })()

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Warehouse"
          subtitle={liveEventQ.data ? `${liveEventQ.data.name} · declared pool, per-bar dispatch, activity feed` : 'No live event'}
          actions={
            liveEventQ.data ? (
              <Button variant="primary" onClick={() => setInvoiceModalOpen(true)}>
                <span className="flex items-center gap-1.5">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Upload Invoice
                </span>
              </Button>
            ) : undefined
          }
        />
      </div>

      {/* Invoice upload modal — untouched */}
      <UploadInvoiceModal
        isOpen={invoiceModalOpen}
        onClose={() => setInvoiceModalOpen(false)}
        eventId={liveEventQ.data?.id ?? null}
      />

      {liveEventQ.isLoading ? (
        <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
          <div className="inline-flex items-center gap-2">
            <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
            Loading…
          </div>
        </div>
      ) : !liveEventQ.data ? (
        // Full-page replacement — deliberately distinct from the
        // table-scoped "no invoices yet" empty state below, which
        // renders WITH the rest of the page chrome (MetricTiles,
        // activity feed) still visible around it. Different
        // situations: no event to show anything for, vs. an event
        // with genuinely nothing invoiced yet.
        <EmptyState
          headline="No live event"
          body="The warehouse view follows the LIVE event. Activate the event from the Events page to see its declared storage here."
        />
      ) : (
        <>
          {/* KPI strip — sourced from the SAME query as the table below
              (useEventWarehouseSummary), not the event-storage-pool summary.
              Previously these read useStorageSummary (event_stock_items),
              which is empty whenever the wizard's Storage tab was skipped —
              showing 0 for everything even when the table right below had
              real invoiced rows. See the "Warehouse KPI cards" bug report. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
            <MetricTile label="Total items" value={eventSummary ? String(eventSummary.total_products) : '—'}>
              <span className="text-[11px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>distinct products</span>
            </MetricTile>
            <MetricTile label="Total quantity" value={eventSummary ? fmtQty(eventSummary.total_qty) : '—'} accent="cyan">
              <span className="text-[11px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>units invoiced</span>
            </MetricTile>
            <MetricTile label="Active allocations" value={eventSummary ? fmtQty(eventSummary.total_dispatched_qty) : '—'} accent="violet">
              <span className="text-[11px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>dispatched to bars</span>
            </MetricTile>
            <MetricTile label="Total value" value={eventSummary ? fmtEur(String(eventSummary.total_value_cents / 100)) : '—'} accent="green">
              <span className="text-[11px] mt-0.5" style={{ color: 'var(--v-text-dim)' }}>invoiced cost</span>
            </MetricTile>
          </div>

          {/* Main: inventory table + activity sidebar */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4">
            {/* T11.5 — event-scoped warehouse table (was: 'Inventory' from
                event_storage). One row per product: invoiced for this event,
                dispatched to bars, remaining. */}
            <div
              className="overflow-hidden"
              style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
            >
              <div
                className="flex items-center justify-between gap-3 px-5 py-4 flex-wrap"
                style={{ borderBottom: '0.5px solid var(--v-border)' }}
              >
                <div>
                  <h2 className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>Warehouse</h2>
                  <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>
                    Everything invoiced for this Sundance, with what bars have already taken.
                  </p>
                </div>
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search product or category…"
                  className={`${inputCls} w-64`}
                />
              </div>

              {eventSummaryQ.isLoading ? (
                <div className="px-5 py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
                  <div className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                    Loading…
                  </div>
                </div>
              ) : !eventSummaryQ.data || eventSummaryQ.data.rows.length === 0 ? (
                <div className="px-5 py-8">
                  <EmptyState
                    headline="No invoices yet for this event"
                    body="Upload one above to get started."
                  />
                </div>
              ) : visibleRows.length === 0 ? (
                <div className="px-5 py-8">
                  <EmptyState headline="No items match" body="Try a different search." />
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
                      <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Product</th>
                      <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Category</th>
                      <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Bought</th>
                      <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Dispatched</th>
                      <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Remaining</th>
                      <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((r) => {
                      const rem = Number(r.remaining_qty)
                      const status = remainingStatus(rem)
                      return (
                        <tr
                          key={r.product_id ?? r.product_name}
                          className="transition-colors last:border-0"
                          style={{ borderBottom: '0.5px solid var(--v-border)' }}
                          onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                        >
                          <td className="px-5 py-3 font-medium" style={{ color: 'var(--v-text)' }}>{r.product_name}</td>
                          <td className="px-5 py-3" style={{ color: 'var(--v-text-muted)' }}>{r.category ?? '—'}</td>
                          <td className="px-5 py-3 text-right tabular-nums" style={{ color: 'var(--v-text-muted)' }}>{r.invoiced_qty}</td>
                          <td className="px-5 py-3 text-right tabular-nums" style={{ color: 'var(--v-text-dim)' }}>{r.dispatched_qty}</td>
                          <td className="px-5 py-3 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <span className="tabular-nums" style={{ color: 'var(--v-text)' }}>{r.remaining_qty}</span>
                              <Badge variant={REMAINING_BADGE[status]}>{REMAINING_LABEL[status]}</Badge>
                            </div>
                          </td>
                          <td className="px-5 py-3 text-right tabular-nums" style={{ color: 'var(--v-text-muted)' }}>
                            {fmtEur(String(r.invoiced_value_cents / 100))}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>

            {/* Activity feed */}
            <div
              className="overflow-hidden"
              style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
            >
              <div className="px-5 py-4" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
                <h2 className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>Activity</h2>
                <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>Recent dispatches</p>
              </div>
              {activityQ.isLoading ? (
                <div className="px-5 py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
                  <div className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                    Loading…
                  </div>
                </div>
              ) : activity.length === 0 ? (
                <div className="px-5 py-8">
                  <EmptyState headline="No dispatches yet" body="Dispatch activity for this event will show up here." />
                </div>
              ) : (
                <ul>
                  {activity.map((a: ActivityFeedRow) => (
                    <li
                      key={a.id}
                      className="px-5 py-3 transition-colors"
                      style={{ borderBottom: '0.5px solid var(--v-border)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-medium truncate" style={{ color: 'var(--v-text)' }}>
                          {fmtQty(a.qty_allocated)}× {a.item_name}
                        </span>
                        <span className="text-xs shrink-0" style={{ color: 'var(--v-text-dim)' }}>
                          {fmtTimeAgo(a.dispatched_at)}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs flex-wrap" style={{ color: 'var(--v-text-muted)' }}>
                        <span>Dispatch · {a.bar_name}</span>
                        {a.user_name && (
                          <span style={{ color: 'var(--v-text-dim)' }}>· {a.user_name}</span>
                        )}
                        {a.user_role && (
                          <Badge variant="dim">{a.user_role}</Badge>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
