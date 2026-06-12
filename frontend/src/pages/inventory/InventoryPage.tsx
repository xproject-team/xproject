/**
 * InventoryPage — per-bar dispatch UI (rewritten for Phase 2.5).
 *
 * The owner uses this page to move bottles/kegs from the declared
 * event storage pool (event_stock_items) out to specific bars. Each
 * dispatch creates a row in event_stock_bar_allocations; the
 * Warehouse page's activity feed and KPIs update automatically via
 * TanStack Query invalidation on mutation success.
 *
 * Layout:
 *   Header: event picker (default LIVE event)
 *   Body:   one card per bar in the event
 *           - top: list of items already dispatched to this bar with
 *                  cumulative qtys (sums history-preserving rows)
 *           - bottom: '+ Dispatch more' form
 *                     item dropdown (only items with qty_available>0)
 *                     qty input (capped at qty_available)
 *                     Dispatch button -> POST /allocations
 *
 * Old Slesh-product allocation view (bar_stock-based) preserved at
 * InventoryPage.tsx.barstock-bak. The /inventory/allocate route still
 * works for the existing Slesh-product bulk allocation flow.
 */
import { useMemo, useState } from 'react'

import { useBarsForEvent } from '@/features/dashboard/hooks'
import { useEvents } from '@/features/events/hooks'
import {
  useBarAllocations,
  useCreateDispatch,
  useStorageSummary,
} from '@/features/event_storage/hooks'
import type {
  BarAllocationSummary,
  StorageSummaryRow,
} from '@/features/event_storage/types'

type EventRow = {
  id: string
  name: string
  status: string
}

type Bar = {
  id: string
  name: string
  is_active?: boolean
  bar_type?: string
}

// ─── Helpers ─────────────────────────────────────────────────────────

function fmtQty(value: string): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return value
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

// ─── Page ────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const eventsQ = useEvents()
  const events = ((eventsQ.data ?? []) as EventRow[]).filter(
    (e) => e.status !== 'COMPLETED' && e.status !== 'completed',
  )
  const defaultEventId = useMemo(() => {
    if (events.length === 0) return undefined
    const live = events.find(
      (e) => e.status === 'LIVE' || e.status === 'live',
    )
    return (live ?? events[0]).id
  }, [events])

  const [eventId, setEventId] = useState<string | undefined>(undefined)
  const effectiveEventId = eventId ?? defaultEventId

  const barsQ = useBarsForEvent(effectiveEventId)
  const summaryQ = useStorageSummary(effectiveEventId)
  const allocationsQ = useBarAllocations(effectiveEventId)

  const bars = (barsQ.data ?? []) as Bar[]
  const summary = summaryQ.data
  const allocations = (allocationsQ.data ?? []) as BarAllocationSummary[]

  // Lookup map: bar_id -> per-bar allocation summary
  const allocByBar = useMemo(() => {
    const m: Record<string, BarAllocationSummary> = {}
    allocations.forEach((a) => {
      m[a.bar_id] = a
    })
    return m
  }, [allocations])

  // ─── Loading / empty ───────────────────────────────────────────────
  if (eventsQ.isLoading) {
    return <PageShell><p className="text-slate-500">Loading events…</p></PageShell>
  }
  if (events.length === 0) {
    return (
      <PageShell>
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
          <h2 className="text-lg font-semibold text-slate-800">No events</h2>
          <p className="mt-2 text-sm text-slate-500">
            Create an event via the wizard to dispatch inventory.
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
          <h1 className="text-3xl font-bold text-slate-800">Inventory</h1>
          <p className="mt-1 text-sm text-slate-500">
            Dispatch bottles &amp; kegs from the warehouse pool to each bar
          </p>
        </div>
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

      {/* Pool strip */}
      <div className="mt-6 rounded-lg border border-blue-200 bg-blue-50 px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
          Storage pool
        </p>
        <p className="mt-1 text-sm text-blue-900">
          {summary ? (
            <>
              <span className="font-semibold">
                {summary.total_items} items
              </span>{' '}
              · {fmtQty(summary.total_qty_received)} units declared ·{' '}
              {fmtQty(summary.total_qty_allocated)} already dispatched
            </>
          ) : (
            'Loading…'
          )}
        </p>
      </div>

      {/* Bar cards */}
      {summaryQ.isLoading ? (
        <p className="mt-6 text-center text-sm text-slate-500">
          Loading inventory…
        </p>
      ) : !summary || summary.rows.length === 0 ? (
        <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-5 py-6 text-center">
          <p className="text-sm font-medium text-amber-900">
            No storage declared for this event yet.
          </p>
          <p className="mt-1 text-xs text-amber-700">
            Open the event in the wizard → Storage tab to declare items.
          </p>
        </div>
      ) : bars.length === 0 ? (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white px-5 py-6 text-center">
          <p className="text-sm text-slate-500">
            This event has no bars yet. Add bars via the wizard.
          </p>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {bars
            .filter((b) => b.is_active !== false)
            .map((bar) => (
              <BarCard
                key={bar.id}
                bar={bar}
                eventId={effectiveEventId!}
                summaryRows={summary.rows}
                existing={allocByBar[bar.id]}
              />
            ))}
        </div>
      )}
    </PageShell>
  )
}

// ─── Bar card ────────────────────────────────────────────────────────

function BarCard({
  bar,
  eventId,
  summaryRows,
  existing,
}: {
  bar: Bar
  eventId: string
  summaryRows: StorageSummaryRow[]
  existing: BarAllocationSummary | undefined
}) {
  const [open, setOpen] = useState(false)
  const [selectedSupplierProductId, setSelectedSupplierProductId] =
    useState<string>('')
  const [qty, setQty] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const dispatchMut = useCreateDispatch(eventId)

  // Items still available for dispatch (qty_available > 0)
  const availableItems = useMemo(
    () => summaryRows.filter((r) => Number(r.qty_available) > 0),
    [summaryRows],
  )

  const selected = availableItems.find(
    (r) => r.supplier_product_id === selectedSupplierProductId,
  )
  const maxQty = selected ? Number(selected.qty_available) : 0

  const reset = () => {
    setOpen(false)
    setSelectedSupplierProductId('')
    setQty('')
    setError(null)
  }

  const onSubmit = async () => {
    setError(null)
    const n = Number(qty)
    if (!selectedSupplierProductId) {
      setError('Pick an item.')
      return
    }
    if (!Number.isFinite(n) || n <= 0) {
      setError('Qty must be > 0.')
      return
    }
    if (n > maxQty) {
      setError(`Only ${maxQty} available in warehouse.`)
      return
    }
    try {
      await dispatchMut.mutateAsync({
        supplier_product_id: selectedSupplierProductId,
        bar_id: bar.id,
        qty_allocated: String(n),
      })
      reset()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Dispatch failed.')
    }
  }

  const items = existing?.items ?? []

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {/* Card header */}
      <div className="border-b border-slate-200 px-5 py-3">
        <h3 className="text-base font-semibold text-slate-800">{bar.name}</h3>
        <p className="text-xs text-slate-500">
          {items.length === 0
            ? 'Nothing dispatched yet'
            : `${items.length} item${items.length === 1 ? '' : 's'} dispatched`}
        </p>
      </div>

      {/* Current allocations */}
      {items.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {items.map((it) => (
            <li
              key={it.supplier_product_id}
              className="flex items-center justify-between px-5 py-2 text-sm"
            >
              <span className="text-slate-700">{it.item_name}</span>
              <span className="font-mono font-semibold text-slate-800">
                {fmtQty(it.qty_total_allocated)} {it.unit}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Dispatch form / button */}
      <div className="border-t border-slate-100 p-4">
        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            disabled={availableItems.length === 0}
            className="w-full rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {availableItems.length === 0
              ? 'No items left in warehouse'
              : '+ Dispatch more'}
          </button>
        ) : (
          <div className="space-y-2">
            <select
              value={selectedSupplierProductId}
              onChange={(e) => {
                setSelectedSupplierProductId(e.target.value)
                setQty('')
                setError(null)
              }}
              className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">— pick item —</option>
              {availableItems.map((r) => (
                <option key={r.supplier_product_id} value={r.supplier_product_id}>
                  {r.item_name} ({fmtQty(r.qty_available)} {r.unit} avail)
                </option>
              ))}
            </select>
            <input
              type="number"
              min={0}
              max={maxQty || undefined}
              step={1}
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                setError(null)
              }}
              placeholder={selected ? `qty (max ${maxQty})` : 'qty'}
              disabled={!selected}
              className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-50"
            />
            {error && (
              <p className="text-xs text-red-600">{error}</p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onSubmit}
                disabled={
                  dispatchMut.isPending || !selectedSupplierProductId || !qty
                }
                className="flex-1 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {dispatchMut.isPending ? 'Dispatching…' : 'Dispatch'}
              </button>
              <button
                type="button"
                onClick={reset}
                disabled={dispatchMut.isPending}
                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Shell ───────────────────────────────────────────────────────────

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="p-8">{children}</div>
}
