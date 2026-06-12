/**
 * WarehousePage — Owner's event storage view (post-Phase-2 rewrite).
 *
 * Replaces the scan-based invoice reconciliation flow with the new
 * event_storage data model:
 *   - Pool of bottles/kegs comes from event_stock_items (declared via
 *     Event Create wizard tab 7 "Storage").
 *   - Per-bar dispatches come from event_stock_bar_allocations.
 *   - Activity feed is the dispatch log ordered newest-first.
 *
 * Event-scoped: defaults to the LIVE event if one exists, otherwise
 * the most recently updated non-COMPLETED event. Event picker lets
 * the owner switch context.
 *
 * What's gone vs the old scan flow:
 *   - "+ New Delivery" button (deliveries are declared in the wizard now)
 *   - AT RISK KPI (Gap 1: delete for Sundance 1)
 *   - PENDING REVIEWS KPI (no scan flow -> no unexpected scans)
 *   - All useInventoryGrid / useInventoryKpis / usePendingDeliveries /
 *     useActivityFeed (scan) hooks
 *
 * The old scan/invoice/pending-review pages (/warehouse/scan,
 * /warehouse/pending-review) remain routable by direct URL but are
 * not linked from this page. They will be demolished post-Sundance.
 *
 * Old file preserved as WarehousePage.tsx.scan-bak.
 */
import { useMemo, useState } from 'react'

import { useEvents } from '@/features/events/hooks'
import {
  useActivityFeed,
  useStorageSummary,
} from '@/features/event_storage/hooks'
import type {
  ActivityFeedRow,
  StorageSummaryRow,
} from '@/features/event_storage/types'

type EventRow = {
  id: string
  name: string
  status: string
  updated_at?: string
}

// ─── Helpers ─────────────────────────────────────────────────────────

const EUR = new Intl.NumberFormat('it-IT', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

function fmtEur(value: string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return EUR.format(n)
}

function fmtQty(value: string): string {
  // Display Decimals as integers when whole, else with 2 dp
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

// ─── Page ────────────────────────────────────────────────────────────

export default function WarehousePage() {
  const eventsQ = useEvents()
  const events = ((eventsQ.data ?? []) as EventRow[]).filter(
    (e) => e.status !== 'COMPLETED' && e.status !== 'completed',
  )

  // Default to LIVE event > first event in the list
  const defaultEventId = useMemo(() => {
    if (events.length === 0) return undefined
    const live = events.find(
      (e) => e.status === 'LIVE' || e.status === 'live',
    )
    if (live) return live.id
    return events[0].id
  }, [events])

  const [eventId, setEventId] = useState<string | undefined>(undefined)
  const effectiveEventId = eventId ?? defaultEventId

  const summaryQ = useStorageSummary(effectiveEventId)
  const activityQ = useActivityFeed(effectiveEventId, 30)

  const summary = summaryQ.data
  const activity = activityQ.data ?? []

  // ─── Filter rows by search ─────────────────────────────────────────
  const [search, setSearch] = useState('')
  const filteredRows: StorageSummaryRow[] = useMemo(() => {
    const rows = summary?.rows ?? []
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(
      (r) =>
        r.item_name.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q),
    )
  }, [summary, search])

  // ─── Loading / empty states ────────────────────────────────────────
  if (eventsQ.isLoading) {
    return <PageShell><p className="text-slate-500">Loading events…</p></PageShell>
  }

  if (events.length === 0) {
    return (
      <PageShell>
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
          <h2 className="text-lg font-semibold text-slate-800">No events</h2>
          <p className="mt-2 text-sm text-slate-500">
            Create an event with storage entries via the event wizard to
            populate the warehouse view.
          </p>
        </div>
      </PageShell>
    )
  }

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-800">
            Warehouse Management
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Declared pool, per-bar dispatch, and activity feed
          </p>
        </div>
        {/* Event picker */}
        <select
          value={effectiveEventId ?? ''}
          onChange={(e) => setEventId(e.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          {events.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name} — {e.status}
            </option>
          ))}
        </select>
      </div>

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
        {/* Inventory table */}
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h2 className="text-base font-semibold text-slate-800">
              Inventory
            </h2>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search product or category…"
              className="w-72 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {summaryQ.isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              Loading inventory…
            </p>
          ) : filteredRows.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              {search
                ? 'No items match your search.'
                : 'No storage declared for this event yet. Open the event in the wizard → Storage tab.'}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <th className="px-5 py-3 text-left">Product</th>
                  <th className="px-5 py-3 text-left">Category</th>
                  <th className="px-5 py-3 text-right">In Stock</th>
                  <th className="px-5 py-3 text-right">Allocated</th>
                  <th className="px-5 py-3 text-right">Available</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((r) => (
                  <tr
                    key={r.supplier_product_id}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                  >
                    <td className="px-5 py-3 font-medium text-slate-800">
                      {r.item_name}
                    </td>
                    <td className="px-5 py-3 text-slate-500">
                      {r.category}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-slate-700">
                      {fmtQty(r.qty_received)} {r.unit}
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-slate-700">
                      {fmtQty(r.qty_allocated)}
                    </td>
                    <td className="px-5 py-3 text-right font-mono font-semibold text-slate-800">
                      {fmtQty(r.qty_available)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Activity sidebar */}
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="text-base font-semibold text-slate-800">
              Activity
            </h2>
            <p className="text-xs text-slate-500">Recent dispatches</p>
          </div>
          {activityQ.isLoading ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              Loading…
            </p>
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
    </PageShell>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="p-8">{children}</div>
}

function KpiTile({
  label,
  value,
  sub,
}: {
  label: string
  value: string | number
  sub: string
}) {
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
