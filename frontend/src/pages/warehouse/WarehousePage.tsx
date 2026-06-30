/**
 * WarehousePage — event storage view, LIVE event only.
 *
 * Locks onto the tenant's single LIVE event (no picker). The whole
 * point of the warehouse view during operations is to monitor THE
 * event that's happening now; historical browsing is out of scope
 * for Sundance 1.
 *
 * Reads:
 *   useLiveEvent          single source of truth for which event
 *   useStorageSummary     KPIs + per-item inventory table
 *   useActivityFeed       dispatch history (right sidebar)
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
  useStorageSummary,
} from '@/features/event_storage/hooks'
import type {
  ActivityFeedRow,
} from '@/features/event_storage/types'

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

  const summaryQ = useStorageSummary(eventId)
  const activityQ = useActivityFeed(eventId, 30)

  const summary = summaryQ.data
  const activity = activityQ.data ?? []

  const [search, setSearch] = useState('')

  if (liveEventQ.isLoading) {
    return <Shell><p className="text-slate-500">Loading…</p></Shell>
  }
  if (!liveEventQ.data) {
    return (
      <Shell>
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
          <h2 className="text-lg font-semibold text-slate-800">No live event</h2>
          <p className="mt-2 text-sm text-slate-500">
            The warehouse view follows the LIVE event. Activate the event
            from the Events page to see its declared storage here.
          </p>
        </div>
      </Shell>
    )
  }

  return (
    <Shell>
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">
            Warehouse Management
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {liveEventQ.data.name} · declared pool, per-bar dispatch, activity feed
          </p>
        </div>
        <button
          type="button"
          onClick={() => setInvoiceModalOpen(true)}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-[#1ABC9C] hover:bg-[#17a589] px-4 py-2 text-sm font-semibold text-white"
        >
          <span className="text-base leading-none">+</span> Upload Invoice
        </button>
      </div>

      {/* Invoice upload modal */}
      <UploadInvoiceModal
        isOpen={invoiceModalOpen}
        onClose={() => setInvoiceModalOpen(false)}
        eventId={liveEventQ.data?.id ?? null}
      />

      {/* KPI strip */}
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile
          label="TOTAL ITEMS"
          value={summary?.total_items ?? '—'}
          sub="distinct products"
        />
        <KpiTile
          label="TOTAL QUANTITY"
          value={summary ? fmtQty(summary.total_qty_received) : '—'}
          sub="units declared"
        />
        <KpiTile
          label="ACTIVE ALLOCATIONS"
          value={summary ? fmtQty(summary.total_qty_allocated) : '—'}
          sub="dispatched to bars"
        />
        <KpiTile
          label="TOTAL VALUE"
          value={summary ? fmtEur(summary.total_line_value_eur) : '—'}
          sub="invoiced cost"
        />
      </div>

            {/* Main: inventory table + activity sidebar */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
        {/* T11.5 — event-scoped warehouse table (was: 'Inventory' from
            event_storage). One row per product: invoiced for this event,
            dispatched to bars, remaining. Color-coded: red = negative
            (over-dispatched), amber = low (<5 left), green = healthy. */}
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <div>
              <h2 className="text-base font-semibold text-slate-800">Warehouse</h2>
              <p className="text-xs text-slate-500">
                Everything invoiced for this Sundance, with what bars have already taken.
              </p>
            </div>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search product or category…"
              className="w-72 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          {eventSummaryQ.isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">Loading…</p>
          ) : !eventSummaryQ.data || eventSummaryQ.data.rows.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              No invoices yet for this event. Upload one above to get started.
            </p>
          ) : (() => {
            const q = search.trim().toLowerCase()
            const visible = q
              ? eventSummaryQ.data.rows.filter(
                  (r) =>
                    r.product_name.toLowerCase().includes(q) ||
                    (r.category ?? '').toLowerCase().includes(q),
                )
              : eventSummaryQ.data.rows
            if (visible.length === 0) {
              return (
                <p className="px-5 py-8 text-center text-sm text-slate-500">
                  No items match your search.
                </p>
              )
            }
            return (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                    <th className="px-5 py-3 text-left">Product</th>
                    <th className="px-5 py-3 text-left">Category</th>
                    <th className="px-5 py-3 text-right">Bought</th>
                    <th className="px-5 py-3 text-right">Dispatched</th>
                    <th className="px-5 py-3 text-right">Remaining</th>
                    <th className="px-5 py-3 text-right">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((r) => {
                    const rem = Number(r.remaining_qty)
                    const remClass =
                      rem < 0
                        ? 'text-red-600'
                        : rem < 5
                          ? 'text-amber-600'
                          : 'text-emerald-700'
                    return (
                      <tr
                        key={r.product_id ?? r.product_name}
                        className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                      >
                        <td className="px-5 py-3 font-medium text-slate-800">{r.product_name}</td>
                        <td className="px-5 py-3 text-slate-500">{r.category ?? '—'}</td>
                        <td className="px-5 py-3 text-right font-mono text-slate-700">{r.invoiced_qty}</td>
                        <td className="px-5 py-3 text-right font-mono text-slate-500">{r.dispatched_qty}</td>
                        <td className={`px-5 py-3 text-right font-mono font-semibold ${remClass}`}>{r.remaining_qty}</td>
                        <td className="px-5 py-3 text-right font-mono text-slate-700">
                          € {(r.invoiced_value_cents / 100).toFixed(2)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )
          })()}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="text-base font-semibold text-slate-800">Activity</h2>
            <p className="text-xs text-slate-500">Recent dispatches</p>
          </div>
          {activityQ.isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">Loading…</p>
          ) : activity.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              No dispatches yet.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {activity.map((a: ActivityFeedRow) => (
                <li key={a.id} className="px-5 py-3">
                  <div className="flex items-baseline justify-between">
                    <span className="font-medium text-slate-800">
                      {fmtQty(a.qty_allocated)}× {a.item_name}
                    </span>
                    <span className="text-xs text-slate-400">
                      {fmtTimeAgo(a.dispatched_at)}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                    <span>Dispatch · {a.bar_name}</span>
                    {a.user_name && (
                      <span className="text-slate-400">· {a.user_name}</span>
                    )}
                    {a.user_role && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
                        {a.user_role}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-8">{children}</div>
}

function KpiTile({
  label, value, sub,
}: { label: string; value: string | number; sub: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-3xl font-bold text-blue-600">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{sub}</p>
    </div>
  )
}
