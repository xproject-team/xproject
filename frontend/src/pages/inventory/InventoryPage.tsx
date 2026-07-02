/**
 * InventoryPage — per-bar stock "box" grid, LIVE event only.
 *
 * The operations view during a live event — the missing link between
 * Warehouse (total invoiced supply) and Dashboard (live monitoring).
 * One box per drinks/food bar, showing that bar's CURRENT stock
 * (same data + math as the Dashboard bar card's stock section) with
 * an inline "+ Add bottle" action to charge it from the warehouse
 * pool. Recharge/service bars (Accrediti, CASSA) hold no bottles and
 * are omitted from the grid entirely.
 *
 * Reuses three already-proven, already-wired pieces rather than
 * introducing anything new:
 *   useBarSupplierStock   same stock query the Dashboard bar-card
 *                         popup (BarDetailOverlay's StockTable) reads
 *   useChargeBarDispatch  same dispatch mutation the Charge Bars page
 *                         uses — POST /event-storage/allocations,
 *                         already invalidates bar-supplier-stock
 *   useStorageSummary     same event_stock_items-backed "declared
 *                         pool" the picker draws its available items
 *                         from (StorageSummaryRow.qty_available)
 *
 * One gap flagged, not silently worked around: on events where the
 * wizard's Storage tab was skipped (event_stock_items empty), boxes
 * still correctly show any stock that was already dispatched in the
 * past (event_stock_bar_allocations is a separate table — see the
 * Inventory/Warehouse empty-state bug report from the prior chunk),
 * but the "+ Add bottle" picker will be empty — dispatch can only
 * draw from the declared pool. The modal says so rather than
 * pretending the button works.
 *
 * No backend changes. Charge Bars page (events/:id/charge-bars) is
 * untouched and remains a bulk-entry alternative.
 */
import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useBarsForEvent, useBarSupplierStock, useLiveEvent } from '@/features/dashboard/hooks'
import type { BarSupplierStockItemDTO } from '@/features/dashboard/hooks'
import { useStorageSummary } from '@/features/event_storage/hooks'
import type { StorageSummaryRow } from '@/features/event_storage/types'
import { useChargeBarDispatch } from '@/features/event_storage/useChargeBars'
import type { BarRow } from '@/lib/mockData'

type StockStatus = 'healthy' | 'low' | 'critical'

const BOX_BAR_TYPES = new Set(['drinks', 'food', 'mixed'])

const STATUS_COLOR: Record<StockStatus, string> = {
  healthy: '#16A34A',
  low: '#D97706',
  critical: '#DC2626',
}
const STATUS_BG: Record<StockStatus, string> = {
  healthy: '#DCFCE7',
  low: '#FEF3C7',
  critical: '#FEE2E2',
}
const STATUS_LABEL: Record<StockStatus, string> = {
  healthy: 'Healthy',
  low: 'Low Stock',
  critical: 'Critical',
}

function fmtQty(value: string | number): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function isStockStatus(s: string | undefined): s is StockStatus {
  return s === 'healthy' || s === 'low' || s === 'critical'
}

// ─── Page ────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const liveEventQ = useLiveEvent()
  const eventId = liveEventQ.data?.id
  const qc = useQueryClient()

  const barsQ = useBarsForEvent(eventId)
  const stockQ = useBarSupplierStock(eventId)
  const summaryQ = useStorageSummary(eventId)
  const dispatchMut = useChargeBarDispatch(eventId ?? '')

  const [addBottleBarId, setAddBottleBarId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const boxBars = useMemo(
    () => ((barsQ.data ?? []) as BarRow[]).filter(
      (b) => b.is_active !== false && BOX_BAR_TYPES.has(b.bar_type as string),
    ),
    [barsQ.data],
  )

  const itemsByBar = useMemo(() => {
    const m = new Map<string, BarSupplierStockItemDTO[]>()
    for (const item of stockQ.data?.items ?? []) {
      const list = m.get(item.bar_id) ?? []
      list.push(item)
      m.set(item.bar_id, list)
    }
    return m
  }, [stockQ.data])

  const statusByBar = useMemo(() => {
    const m = new Map<string, StockStatus>()
    for (const b of stockQ.data?.by_bar ?? []) {
      if (isStockStatus(b.status)) m.set(b.bar_id, b.status)
    }
    return m
  }, [stockQ.data])

  const availableItems = useMemo(
    () => (summaryQ.data?.rows ?? []).filter((r) => Number(r.qty_available) > 0),
    [summaryQ.data],
  )

  const totalUnitsAtBars = useMemo(
    () => (stockQ.data?.items ?? []).reduce((sum, i) => sum + i.dispatched_units, 0),
    [stockQ.data],
  )
  const totalAvailableToDispatch = useMemo(
    () => availableItems.reduce((sum, r) => sum + Number(r.qty_available), 0),
    [availableItems],
  )

  const showToast = (msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 3000)
  }

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

  const addBottleBar = boxBars.find((b) => b.id === addBottleBarId) ?? null

  return (
    <Shell>
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-slate-800">
          Inventory — {liveEventQ.data.name}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Live stock at each bar. Add bottles from the warehouse to charge a bar.
        </p>
      </div>

      {/* Summary strip — both halves stay within the same supplier_product
          taxonomy as the boxes below (avoids re-mixing it with the
          products-keyed warehouse_inventory numbers — see the prior
          chunk's Inventory/Warehouse bug report for why that's a trap). */}
      <div className="mt-6 rounded-lg border border-blue-200 bg-blue-50 px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-blue-700">
          Stock overview
        </p>
        <p className="mt-1 text-sm text-blue-900">
          <span className="font-semibold">{fmtQty(totalUnitsAtBars)} units</span> currently at bars
          {' · '}{fmtQty(totalAvailableToDispatch)} units available to dispatch
        </p>
      </div>

      {/* Bar boxes */}
      {barsQ.isLoading ? (
        <p className="mt-6 text-center text-sm text-slate-500">Loading…</p>
      ) : boxBars.length === 0 ? (
        <Empty
          title="No drinks or food bars yet"
          body="This event has no drinks or food bars yet. Configure bars in the wizard."
        />
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {boxBars.map((bar) => (
            <BarBox
              key={bar.id}
              bar={bar}
              items={itemsByBar.get(bar.id) ?? []}
              status={statusByBar.get(bar.id)}
              stockLoading={stockQ.isLoading}
              stockError={stockQ.isError}
              onAddBottle={() => setAddBottleBarId(bar.id)}
            />
          ))}
        </div>
      )}

      {/* Add bottle modal */}
      {addBottleBar && eventId && (
        <AddBottleModal
          bar={addBottleBar}
          availableItems={availableItems}
          dispatchMut={dispatchMut}
          onClose={() => setAddBottleBarId(null)}
          onSuccess={(msg) => {
            showToast(msg)
            // useChargeBarDispatch already invalidates event-storage
            // summary/by-bar/activity + dashboard's bar-supplier-stock.
            // It does NOT know about the Warehouse page's separate
            // useEventWarehouseSummary query — invalidate that one here
            // so the Warehouse KPI cards + table pick up the dispatch too.
            qc.invalidateQueries({ queryKey: ['warehouse', 'event-summary', eventId] })
          }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-6 z-50 rounded-lg bg-slate-900 px-4 py-3 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </Shell>
  )
}

// ─── Bar box ─────────────────────────────────────────────────────────

function BarBox({
  bar, items, status, stockLoading, stockError, onAddBottle,
}: {
  bar: BarRow
  items: BarSupplierStockItemDTO[]
  status: StockStatus | undefined
  stockLoading: boolean
  stockError: boolean
  onAddBottle: () => void
}) {
  const sorted = useMemo(() => [...items].sort((a, b) => {
    const sev = (s: string) => (s === 'critical' ? 0 : s === 'low' ? 1 : 2)
    if (sev(a.status) !== sev(b.status)) return sev(a.status) - sev(b.status)
    return a.remaining_pct - b.remaining_pct
  }), [items])

  return (
    <div className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800 truncate" title={bar.name}>
          {bar.name}
        </h3>
        {status && (
          <span
            className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: STATUS_COLOR[status], backgroundColor: STATUS_BG[status] }}
          >
            {STATUS_LABEL[status]}
          </span>
        )}
      </div>

      <div className="mt-3 flex-1 space-y-2">
        {stockError ? (
          <p className="rounded-md border border-dashed border-red-200 px-3 py-4 text-center text-xs text-red-500">
            Failed to load stock.
          </p>
        ) : stockLoading ? (
          <p className="py-4 text-center text-xs text-slate-400">Loading…</p>
        ) : sorted.length === 0 ? (
          <p className="rounded-md border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">
            This bar has no stock yet. Click + Add bottle to charge it.
          </p>
        ) : (
          sorted.map((r) => {
            const pct = Math.max(0, Math.min(100, r.remaining_pct))
            return (
              <div key={r.supplier_product_id} className="rounded-md border border-slate-100 p-2">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium text-slate-700" title={r.item_name}>
                    {r.item_name}
                  </span>
                  <span
                    className="shrink-0 text-[10px] font-semibold tabular-nums"
                    style={{ color: STATUS_COLOR[r.status] }}
                  >
                    {Math.round(pct)}%
                  </span>
                </div>
                <div
                  className="h-2 w-full overflow-hidden rounded-full"
                  style={{ backgroundColor: STATUS_BG[r.status] }}
                >
                  <div
                    className="h-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: STATUS_COLOR[r.status] }}
                  />
                </div>
                <p className="mt-1 text-[10px] tabular-nums text-slate-500">
                  {Math.round(r.remaining_ml).toLocaleString()} / {Math.round(r.dispatched_ml).toLocaleString()} ml
                </p>
              </div>
            )
          })
        )}
      </div>

      <button
        type="button"
        onClick={onAddBottle}
        className="mt-3 w-full rounded-md bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700"
      >
        + Add bottle
      </button>
    </div>
  )
}

// ─── Add bottle modal ────────────────────────────────────────────────

function AddBottleModal({
  bar, availableItems, dispatchMut, onClose, onSuccess,
}: {
  bar: BarRow
  availableItems: StorageSummaryRow[]
  dispatchMut: ReturnType<typeof useChargeBarDispatch>
  onClose: () => void
  onSuccess: (msg: string) => void
}) {
  const [selectedSpId, setSelectedSpId] = useState('')
  const [qty, setQty] = useState('')
  const [error, setError] = useState<string | null>(null)

  const selected = availableItems.find((r) => r.supplier_product_id === selectedSpId)
  const maxQty = selected ? Number(selected.qty_available) : 0

  const onConfirm = async () => {
    setError(null)
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
      onSuccess(`Charged ${n} ${selected?.unit} of ${selected?.item_name} to ${bar.name}.`)
      onClose()
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
      <div className="w-full max-w-md rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-800">Add bottle — {bar.name}</h2>
            <p className="text-xs text-slate-500">Charge from the warehouse pool</p>
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

        <div className="px-6 py-4">
          {availableItems.length === 0 ? (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
              No items available in the declared warehouse pool. Declare stock via
              the wizard → Storage tab before charging bars.
            </p>
          ) : (
            <div className="space-y-2">
              <select
                value={selectedSpId}
                onChange={(e) => { setSelectedSpId(e.target.value); setQty(''); setError(null) }}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="">— pick item —</option>
                {availableItems.map((r) => (
                  <option key={r.supplier_product_id} value={r.supplier_product_id}>
                    {r.item_name} ({fmtQty(r.qty_available)} {r.unit} available)
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
              <button
                type="button"
                onClick={onConfirm}
                disabled={dispatchMut.isPending || !selectedSpId || !qty}
                className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {dispatchMut.isPending ? 'Confirming…' : 'Confirm'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Shell + Empty ───────────────────────────────────────────────────

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="p-8">{children}</div>
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="mt-6 rounded-lg border border-slate-200 bg-white p-8 text-center">
      <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
      <p className="mt-2 text-sm text-slate-500">{body}</p>
    </div>
  )
}
