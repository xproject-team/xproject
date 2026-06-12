/**
 * InventoryPage — bar tile grid + dispatch modal, LIVE event only.
 *
 * The page locks onto the tenant's single LIVE event. No picker —
 * there's only ever one event being executed at a time. If no event
 * is LIVE the page shows a wait state.
 *
 * Layout:
 *   Header: title (event name shown for context, not selectable)
 *   Pool strip: total items / declared units / already dispatched
 *   Bar tiles: compact grid; click a tile to open the modal
 *   Modal:    items currently in the bar + "charge this bar" form
 *
 * Modal close: × button, backdrop click, ESC key. After a successful
 * dispatch the modal stays open with the refreshed item list so the
 * owner can charge several items in a row.
 *
 * Cross-page sync via TanStack Query invalidation: Warehouse KPIs +
 * activity feed update automatically; Dashboard bar cards update via
 * the storage line added in commit 7.
 */
import { useEffect, useMemo, useState } from 'react'

import { useBarsForEvent, useLiveEvent } from '@/features/dashboard/hooks'
import {
  useActivityFeed,
  useBarAllocations,
  useCreateDispatch,
  useStorageSummary,
} from '@/features/event_storage/hooks'
import type {
  ActivityFeedRow,
  BarAllocationSummary,
  StorageSummaryRow,
} from '@/features/event_storage/types'

type Bar = { id: string; name: string; is_active?: boolean; bar_type?: string }

function fmtQty(value: string): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return value
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

// ─── Page ────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const liveEventQ = useLiveEvent()
  const eventId = liveEventQ.data?.id

  const barsQ = useBarsForEvent(eventId)
  const summaryQ = useStorageSummary(eventId)
  const allocationsQ = useBarAllocations(eventId)

  const bars = (barsQ.data ?? []) as Bar[]
  const summary = summaryQ.data
  const allocations = (allocationsQ.data ?? []) as BarAllocationSummary[]

  const allocByBar = useMemo(() => {
    const m: Record<string, BarAllocationSummary> = {}
    allocations.forEach((a) => { m[a.bar_id] = a })
    return m
  }, [allocations])

  const [openBarId, setOpenBarId] = useState<string | null>(null)
  const openBar = bars.find((b) => b.id === openBarId) ?? null

  if (liveEventQ.isLoading) {
    return <Shell><p className="text-slate-500">Loading…</p></Shell>
  }
  if (!liveEventQ.data) {
    return (
      <Shell>
        <Empty
          title="No live event"
          body="Inventory is only available while an event is LIVE. Activate the event from the Events page when you're ready."
        />
      </Shell>
    )
  }

  return (
    <Shell>
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-slate-800">Inventory</h1>
        <p className="mt-1 text-sm text-slate-500">
          {liveEventQ.data.name} · tap a bar to see what's in it and charge it
        </p>
      </div>

      {/* Pool strip */}
      <div className="mt-6 rounded-lg border border-blue-200 bg-blue-50 px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
          Storage pool
        </p>
        <p className="mt-1 text-sm text-blue-900">
          {summary ? (
            <>
              <span className="font-semibold">{summary.total_items} items</span>
              {' · '}{fmtQty(summary.total_qty_received)} units declared
              {' · '}{fmtQty(summary.total_qty_allocated)} already dispatched
            </>
          ) : 'Loading…'}
        </p>
      </div>

      {/* Bar tiles */}
      {summaryQ.isLoading ? (
        <p className="mt-6 text-center text-sm text-slate-500">Loading…</p>
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
        <Empty title="No bars in this event" body="Add bars via the wizard." />
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {bars
            .filter(
              (b) =>
                b.is_active !== false &&
                (b.bar_type === 'drinks' || b.bar_type === 'mixed'),
            )
            .map((bar) => (
              <BarTile
                key={bar.id}
                bar={bar}
                existing={allocByBar[bar.id]}
                onClick={() => setOpenBarId(bar.id)}
              />
            ))}
        </div>
      )}

      {/* Modal */}
      {openBar && summary && eventId && (
        <DispatchModal
          bar={openBar}
          eventId={eventId}
          summaryRows={summary.rows}
          existing={allocByBar[openBar.id]}
          onClose={() => setOpenBarId(null)}
        />
      )}
    </Shell>
  )
}

// ─── Bar tile ────────────────────────────────────────────────────────

function BarTile({
  bar, existing, onClick,
}: {
  bar: Bar
  existing: BarAllocationSummary | undefined
  onClick: () => void
}) {
  const items = existing?.items ?? []
  const totalUnits = items.reduce(
    (sum, i) => sum + Number(i.qty_total_allocated), 0,
  )
  const empty = items.length === 0

  return (
    <button
      type="button"
      onClick={onClick}
      className={`group relative flex flex-col items-start rounded-lg border bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
        empty
          ? 'border-slate-200 hover:border-slate-300'
          : 'border-blue-200 hover:border-blue-400'
      }`}
    >
      <p className="text-sm font-semibold text-slate-800 line-clamp-2">
        {bar.name}
      </p>
      <div className="mt-3 flex w-full items-baseline justify-between">
        <span className={`text-2xl font-bold ${
          empty ? 'text-slate-300' : 'text-blue-600'
        }`}>
          {empty ? '—' : items.length}
        </span>
        <span className="text-xs text-slate-500">
          {empty ? 'empty' : items.length === 1 ? 'item' : 'items'}
        </span>
      </div>
      {!empty && (
        <p className="mt-1 text-xs text-slate-500">
          {fmtQty(String(totalUnits))} units total
        </p>
      )}
    </button>
  )
}

// ─── Dispatch modal ──────────────────────────────────────────────────

function DispatchModal({
  bar, eventId, summaryRows, existing, onClose,
}: {
  bar: Bar
  eventId: string
  summaryRows: StorageSummaryRow[]
  existing: BarAllocationSummary | undefined
  onClose: () => void
}) {
  const [selectedSpId, setSelectedSpId] = useState<string>('')
  const [qty, setQty] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const dispatchMut = useCreateDispatch(eventId)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const items = existing?.items ?? []
  const availableItems = useMemo(
    () => summaryRows.filter((r) => Number(r.qty_available) > 0),
    [summaryRows],
  )
  const selected = availableItems.find((r) => r.supplier_product_id === selectedSpId)
  const maxQty = selected ? Number(selected.qty_available) : 0

  const onSubmit = async () => {
    setError(null); setFlash(null)
    const n = Number(qty)
    if (!selectedSpId) { setError('Pick an item.'); return }
    if (!Number.isFinite(n) || n <= 0) { setError('Qty must be > 0.'); return }
    if (n > maxQty) { setError(`Only ${maxQty} available.`); return }
    try {
      await dispatchMut.mutateAsync({
        supplier_product_id: selectedSpId,
        bar_id: bar.id,
        qty_allocated: String(n),
      })
      setFlash(`Dispatched ${n} ${selected?.unit} of ${selected?.item_name}.`)
      setSelectedSpId(''); setQty('')
      setTimeout(() => setFlash(null), 2500)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Dispatch failed.')
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-800">{bar.name}</h2>
            <p className="text-xs text-slate-500">Per-bar inventory</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Currently dispatched */}
        <div className="px-6 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Currently in this bar
          </p>
          {items.length === 0 ? (
            <p className="mt-2 rounded-md border border-dashed border-slate-200 px-3 py-4 text-center text-sm text-slate-400">
              Nothing dispatched yet.
            </p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100 rounded-md border border-slate-200">
              {items.map((it) => (
                <li
                  key={it.supplier_product_id}
                  className="flex items-center justify-between px-3 py-2 text-sm"
                >
                  <span className="text-slate-700">{it.item_name}</span>
                  <span className="font-mono font-semibold text-slate-800">
                    {fmtQty(it.qty_total_allocated)} {it.unit}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Recent activity (this bar only) */}
        <BarActivitySection bar={bar} eventId={eventId} />

        {/* Charge form */}
        <div className="border-t border-slate-100 bg-slate-50/60 px-6 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Charge this bar
          </p>
          {availableItems.length === 0 ? (
            <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              No items left in the warehouse pool.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              <select
                value={selectedSpId}
                onChange={(e) => {
                  setSelectedSpId(e.target.value); setQty(''); setError(null)
                }}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                onChange={(e) => { setQty(e.target.value); setError(null) }}
                placeholder={selected ? `qty (max ${maxQty})` : 'qty'}
                disabled={!selected}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-100"
              />
              {error && <p className="text-xs text-red-600">{error}</p>}
              {flash && (
                <p className="rounded-md bg-green-50 px-2 py-1.5 text-xs text-green-800">
                  {flash}
                </p>
              )}
              <button
                type="button"
                onClick={onSubmit}
                disabled={dispatchMut.isPending || !selectedSpId || !qty}
                className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {dispatchMut.isPending ? 'Dispatching…' : 'Dispatch'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Per-bar activity section ────────────────────────────────────────

function BarActivitySection({
  bar, eventId,
}: { bar: Bar; eventId: string }) {
  const activityQ = useActivityFeed(eventId, 15, bar.id)
  const rows = (activityQ.data ?? []) as ActivityFeedRow[]

  return (
    <div className="border-t border-slate-100 px-6 py-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        Recent activity (this bar)
      </p>
      {activityQ.isLoading ? (
        <p className="mt-2 text-xs text-slate-400">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 rounded-md border border-dashed border-slate-200 px-3 py-3 text-center text-xs text-slate-400">
          No activity yet.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-slate-100 rounded-md border border-slate-200">
          {rows.map((a) => (
            <li key={a.id} className="px-3 py-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm text-slate-800">
                  <span className="font-semibold">
                    {Number(a.qty_allocated)}× {a.item_unit}
                  </span>{' '}
                  {a.item_name}
                </span>
                <span className="text-[10px] text-slate-400 whitespace-nowrap">
                  {fmtTimeAgo(a.dispatched_at)}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
                <span>Dispatched</span>
                {a.user_name && (
                  <span className="text-slate-400">· {a.user_name}</span>
                )}
                {a.user_role && (
                  <span className="rounded bg-slate-100 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-600">
                    {a.user_role}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function fmtTimeAgo(iso: string): string {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

// ─── Shell + Empty ───────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-8">{children}</div>
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-8 text-center">
      <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
      <p className="mt-2 text-sm text-slate-500">{body}</p>
    </div>
  )
}
