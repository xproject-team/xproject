/**
 * InventoryPage — per-bar stock "box" grid, LIVE event only.
 *
 * Design-system conversion (Day 11 Phase 3): same data/behavior as
 * before (useBarSupplierStock, useChargeBarDispatch, the name-match
 * bridge to warehouse-invoiced items) — UI-only restyle onto the dark
 * design system used by Events/Bars/Catalog. No hook, type, or backend
 * change.
 *
 * "Not configured" status (Day 11 investigation finding): a bar with NO
 * stock rows at all previously showed no status badge whatsoever — not
 * wrong, but silent. It must not be confused with "healthy" (a bar that
 * has stock and is comfortably above the low-stock threshold). This is
 * derived purely client-side from items.length === 0, which the page
 * already computes — no backend change needed.
 *
 * Reuses already-proven, already-wired pieces rather than introducing
 * anything new:
 *   useBarSupplierStock    same stock query the Dashboard bar-card
 *                          popup (BarDetailOverlay's StockTable) reads
 *   useChargeBarDispatch   same dispatch mutation the Charge Bars page
 *                          uses — POST /event-storage/allocations,
 *                          already invalidates bar-supplier-stock
 *   useEventWarehouseSummary  same query the Warehouse page's KPI
 *                          cards + table read (warehouse_inventory-
 *                          backed, invoice-populated) — the picker's
 *                          "available to dispatch" source
 *   useSupplierProducts    tenant catalog of dispatchable items
 *
 * The "+ Add bottle" picker bug fix: dispatch (POST /event-storage/
 * allocations, unchanged) requires a supplier_product_id. Warehouse's
 * invoice-populated rows (EventWarehouseSummary) are product_id-keyed
 * — supplier_products has NO foreign key to products (see the
 * Inventory/Warehouse bug report from two chunks back), only a
 * best-effort case-insensitive name match, which is exactly what the
 * backend's own InvoiceRepository.get_event_summary already uses to
 * compute the Warehouse table's "Dispatched"/"Remaining" columns. This
 * page does the SAME match client-side (product_name <-> item_name)
 * to resolve a supplier_product_id for dispatch — anything that
 * doesn't match a supplier_product (rare — 8 of 29 products on July 5
 * TEST, mostly water/soda lines) is shown but not selectable, with a
 * note, rather than silently hidden or silently broken.
 *
 * No backend changes. Charge Bars page (events/:id/charge-bars) is
 * untouched and remains a bulk-entry alternative.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useBarsForEvent, useBarSupplierStock, useLiveEvent } from '@/features/dashboard/hooks'
import type { BarSupplierStockItemDTO } from '@/features/dashboard/hooks'
import { useSupplierProducts } from '@/features/event_storage/hooks'
import { useChargeBarDispatch } from '@/features/event_storage/useChargeBars'
import { useEventWarehouseSummary } from '@/features/warehouse/useWarehouse'
import type { BarRow } from '@/lib/mockData'
import { Badge, Button, EmptyState, MetricTile, PageHeader } from '@/design-system/components'
import type { BadgeVariant } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label } from '@/design-system/wizardForm'

interface PickerRow {
  key:                 string   // product_name, lowercased — React key + name-match key
  product_name:        string
  remaining_qty:       string
  supplier_product_id: string | null   // null = no matching supplier_product, not dispatchable
  unit:                string
}

type StockStatus = 'healthy' | 'low' | 'critical' | 'not_configured'

const BOX_BAR_TYPES = new Set(['drinks', 'food', 'mixed'])

const STATUS_BADGE: Record<StockStatus, BadgeVariant> = {
  healthy: 'success',
  low: 'warning',
  critical: 'danger',
  not_configured: 'dim',
}
const STATUS_LABEL: Record<StockStatus, string> = {
  healthy: 'Healthy',
  low: 'Low Stock',
  critical: 'Critical',
  not_configured: 'Not configured',
}
const STATUS_COLOR: Record<'healthy' | 'low' | 'critical', string> = {
  healthy: 'var(--v-green)',
  low: 'var(--v-amber)',
  critical: 'var(--v-pink)',
}

function fmtQty(value: string | number): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function isStockStatus(s: string | undefined): s is 'healthy' | 'low' | 'critical' {
  return s === 'healthy' || s === 'low' || s === 'critical'
}

// A bar with zero stock rows must never read as "healthy" — that was a
// real false positive (Day 11 investigation). Not-configured is its own,
// plainly-labelled state, independent of whatever the aggregate status
// query returned (or didn't). Shared by the card and the detail panel so
// the two never disagree.
function effectiveStockStatus(
  items: BarSupplierStockItemDTO[],
  status: 'healthy' | 'low' | 'critical' | undefined,
): StockStatus {
  return items.length === 0 ? 'not_configured' : (status ?? 'not_configured')
}

// Established modal treatment (see BarDetailOverlay / SalesBreakdownModal /
// RevenueBreakdownModal / EventDetailPage — same values everywhere).
const MODAL_BACKDROP_STYLE = {
  background: 'rgba(8,9,13,0.72)',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
} as const

// Fixed height for the card's bottle-summary block — every card gets the
// same value regardless of how many bottles that bar has (0, 1, or 20),
// so the grid stays a scannable overview instead of growing per-card.
const CARD_LIST_HEIGHT = 138
const CARD_MAX_ROWS = 3

/** Escape-to-close, shared by every modal/panel in this file. */
function useEscapeToClose(onClose: () => void) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
}

// ─── Page ────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const liveEventQ = useLiveEvent()
  const eventId = liveEventQ.data?.id
  const qc = useQueryClient()

  const barsQ = useBarsForEvent(eventId)
  const stockQ = useBarSupplierStock(eventId)
  const warehouseQ = useEventWarehouseSummary(eventId)
  const supplierProductsQ = useSupplierProducts()
  const dispatchMut = useChargeBarDispatch(eventId ?? '')

  const [addBottleBarId, setAddBottleBarId] = useState<string | null>(null)
  const [detailBarId, setDetailBarId] = useState<string | null>(null)
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
    const m = new Map<string, 'healthy' | 'low' | 'critical'>()
    for (const b of stockQ.data?.by_bar ?? []) {
      if (isStockStatus(b.status)) m.set(b.bar_id, b.status)
    }
    return m
  }, [stockQ.data])

  // Name-match bridge: supplier_products has no FK to products, only a
  // best-effort case-insensitive name match (see file header + the
  // backend's InvoiceRepository.get_event_summary, which computes this
  // page's warehouse data the same way).
  const supplierIdByName = useMemo(() => {
    const m = new Map<string, { id: string; unit: string }>()
    for (const sp of supplierProductsQ.data ?? []) {
      m.set(sp.item_name.trim().toLowerCase(), { id: sp.id, unit: sp.default_unit })
    }
    return m
  }, [supplierProductsQ.data])

  const pickerRows = useMemo<PickerRow[]>(() => {
    return (warehouseQ.data?.rows ?? [])
      .filter((r) => Number(r.remaining_qty) > 0)
      .map((r) => {
        const key = r.product_name.trim().toLowerCase()
        const match = supplierIdByName.get(key)
        return {
          key,
          product_name: r.product_name,
          remaining_qty: r.remaining_qty,
          supplier_product_id: match?.id ?? null,
          unit: match?.unit ?? '',
        }
      })
  }, [warehouseQ.data, supplierIdByName])

  const totalUnitsAtBars = useMemo(
    () => (stockQ.data?.items ?? []).reduce((sum, i) => sum + i.dispatched_units, 0),
    [stockQ.data],
  )
  // Sum across ALL warehouse-remaining products, not just the
  // dispatchable (name-matched) subset — matches what the Warehouse
  // page's own REMAINING column totals to.
  const totalAvailableToDispatch = useMemo(
    () => pickerRows.reduce((sum, r) => sum + Number(r.remaining_qty), 0),
    [pickerRows],
  )

  const showToast = (msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 3000)
  }

  const addBottleBar = boxBars.find((b) => b.id === addBottleBarId) ?? null
  const detailBar = boxBars.find((b) => b.id === detailBarId) ?? null

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Inventory"
          subtitle={liveEventQ.data ? `${liveEventQ.data.name} · Live stock at each bar` : 'No live event'}
        />
      </div>

      {liveEventQ.isLoading ? (
        <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
          <div className="inline-flex items-center gap-2">
            <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
            Loading…
          </div>
        </div>
      ) : !liveEventQ.data ? (
        <EmptyState
          headline="No live event"
          body="Inventory is only available while an event is LIVE. Activate the event from the Events page when you're ready."
        />
      ) : (
        <>
          {/* Summary tiles */}
          <div className="grid grid-cols-2 gap-3 mb-6">
            <MetricTile label="Units at bars" value={fmtQty(totalUnitsAtBars)} accent="cyan" />
            <MetricTile label="Available to dispatch" value={fmtQty(totalAvailableToDispatch)} accent="green" />
          </div>

          {/* Bar boxes */}
          {barsQ.isLoading ? (
            <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>Loading…</div>
          ) : boxBars.length === 0 ? (
            <EmptyState
              headline="No drinks or food bars yet"
              body="This event has no drinks or food bars yet. Configure bars in the wizard."
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 items-stretch">
              {boxBars.map((bar) => (
                <BarBox
                  key={bar.id}
                  bar={bar}
                  items={itemsByBar.get(bar.id) ?? []}
                  status={statusByBar.get(bar.id)}
                  stockLoading={stockQ.isLoading}
                  stockError={stockQ.isError}
                  onOpenDetail={() => setDetailBarId(bar.id)}
                  onAddBottle={() => setAddBottleBarId(bar.id)}
                />
              ))}
            </div>
          )}

          {/* Bar detail panel — hidden (not unmounted) while the Add
              bottle modal is open on top of it, so closing that modal
              returns to the panel instead of closing everything. */}
          {detailBar && !addBottleBar && (
            <BarDetailPanel
              bar={detailBar}
              items={itemsByBar.get(detailBar.id) ?? []}
              status={statusByBar.get(detailBar.id)}
              stockLoading={stockQ.isLoading}
              stockError={stockQ.isError}
              onClose={() => setDetailBarId(null)}
              onAddBottle={() => setAddBottleBarId(detailBar.id)}
            />
          )}

          {/* Add bottle modal — opened either directly from a card
              (detailBarId stays null) or from the detail panel above
              (detailBarId stays set, so the panel reappears on close). */}
          {addBottleBar && eventId && (
            <AddBottleModal
              bar={addBottleBar}
              pickerRows={pickerRows}
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
            <div
              className="fixed bottom-6 left-6 z-50 rounded-lg px-4 py-3 text-sm"
              style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)', color: 'var(--v-text)' }}
            >
              {toast}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Bar box — compact summary card ─────────────────────────────────
//
// Deliberately does NOT list every bottle — that's what made the grid
// grow unusably with stock count (Day 11 follow-up). This card shows
// just enough to triage at a glance; the full list lives in the detail
// panel, opened by clicking anywhere on the card except the button.

function BarBox({
  bar, items, status, stockLoading, stockError, onOpenDetail, onAddBottle,
}: {
  bar: BarRow
  items: BarSupplierStockItemDTO[]
  status: 'healthy' | 'low' | 'critical' | undefined
  stockLoading: boolean
  stockError: boolean
  onOpenDetail: () => void
  onAddBottle: () => void
}) {
  // Lowest-remaining first — the top of this list is "what needs
  // attention", both here (capped preview) and in the detail panel
  // (full list).
  const sortedByLowest = useMemo(
    () => [...items].sort((a, b) => a.remaining_pct - b.remaining_pct),
    [items],
  )
  const preview = sortedByLowest.slice(0, CARD_MAX_ROWS)
  const hiddenCount = sortedByLowest.length - preview.length

  const effectiveStatus = effectiveStockStatus(items, status)
  const totalUnits = useMemo(
    () => items.reduce((sum, i) => sum + i.dispatched_units, 0),
    [items],
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpenDetail() }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpenDetail}
      onKeyDown={handleKeyDown}
      className="flex flex-col h-full p-4 text-left cursor-pointer transition-colors"
      style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--v-border-hover)')}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--v-border)')}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium truncate" style={{ color: 'var(--v-text)' }} title={bar.name}>
          {bar.name}
        </h3>
        <Badge variant={STATUS_BADGE[effectiveStatus]}>{STATUS_LABEL[effectiveStatus]}</Badge>
      </div>

      <p className="mt-1 text-xs" style={{ color: 'var(--v-text-muted)' }}>
        {fmtQty(totalUnits)} units &middot; {items.length} bottle{items.length === 1 ? '' : 's'}
      </p>

      {/* Fixed-height block — identical for every card, whether the bar
          has 0 bottles or 20. */}
      <div className="mt-3" style={{ height: CARD_LIST_HEIGHT }}>
        {stockError ? (
          <p className="px-3 py-4 text-center text-xs" style={{ color: 'var(--v-pink)' }}>
            Failed to load stock.
          </p>
        ) : stockLoading ? (
          <p className="py-4 text-center text-xs" style={{ color: 'var(--v-text-dim)' }}>Loading…</p>
        ) : preview.length === 0 ? (
          <p className="py-4 text-center text-xs" style={{ color: 'var(--v-text-dim)' }}>
            This bar has no stock yet. Click + Add bottle to charge it.
          </p>
        ) : (
          <div className="space-y-2">
            {preview.map((r) => {
              const pct = Math.max(0, Math.min(100, r.remaining_pct))
              const color = STATUS_COLOR[isStockStatus(r.status) ? r.status : 'healthy']
              return (
                <div key={r.supplier_product_id}>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium" style={{ color: 'var(--v-text-muted)' }} title={r.item_name}>
                      {r.item_name}
                    </span>
                    <span className="shrink-0 text-[10px] font-medium tabular-nums" style={{ color }}>
                      {Math.round(pct)}%
                    </span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full" style={{ background: 'var(--v-surface-raised)' }}>
                    <div className="h-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              )
            })}
            {hiddenCount > 0 && (
              <p className="text-[11px]" style={{ color: 'var(--v-text-dim)' }}>+ {hiddenCount} more</p>
            )}
          </div>
        )}
      </div>

      <Button
        variant="secondary"
        onClick={(e) => { e.stopPropagation(); onAddBottle() }}
        className="mt-3 w-full"
      >
        + Add bottle
      </Button>
    </div>
  )
}

// ─── Bar detail panel ────────────────────────────────────────────────
//
// The "bigger picture" view — every bottle, full names, real vertical
// room. Fixed header + footer, only the bottle list scrolls.

function BarDetailPanel({
  bar, items, status, stockLoading, stockError, onClose, onAddBottle,
}: {
  bar: BarRow
  items: BarSupplierStockItemDTO[]
  status: 'healthy' | 'low' | 'critical' | undefined
  stockLoading: boolean
  stockError: boolean
  onClose: () => void
  onAddBottle: () => void
}) {
  useEscapeToClose(onClose)

  const sortedByLowest = useMemo(
    () => [...items].sort((a, b) => a.remaining_pct - b.remaining_pct),
    [items],
  )
  const effectiveStatus = effectiveStockStatus(items, status)
  const totalUnits = useMemo(
    () => items.reduce((sum, i) => sum + i.dispatched_units, 0),
    [items],
  )

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={MODAL_BACKDROP_STYLE}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${bar.name} stock detail`}
        onClick={(e) => e.stopPropagation()}
        className="w-full flex flex-col"
        style={{
          maxWidth: 720,
          maxHeight: '80vh',
          background: 'var(--v-surface-raised)',
          border: '0.5px solid var(--v-border)',
          borderRadius: 'var(--v-radius-lg)',
        }}
      >
        {/* Header — fixed */}
        <header
          className="shrink-0 flex items-center justify-between gap-4 px-6 py-4"
          style={{ borderBottom: '0.5px solid var(--v-border)' }}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <h2 className="text-lg font-medium truncate" style={{ color: 'var(--v-text)' }}>{bar.name}</h2>
            <Badge variant={STATUS_BADGE[effectiveStatus]}>{STATUS_LABEL[effectiveStatus]}</Badge>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <span className="text-xs" style={{ color: 'var(--v-text-muted)' }}>
              {fmtQty(totalUnits)} units &middot; {items.length} bottle{items.length === 1 ? '' : 's'}
            </span>
            <button
              onClick={onClose}
              aria-label="Close"
              className="w-8 h-8 flex items-center justify-center rounded-full transition-colors"
              style={{ border: '0.5px solid var(--v-border)', color: 'var(--v-text-muted)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--v-text)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--v-text-muted)')}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </header>

        {/* Body — the only scrollable region */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {stockError ? (
            <p className="py-8 text-center text-sm" style={{ color: 'var(--v-pink)' }}>Failed to load stock.</p>
          ) : stockLoading ? (
            <p className="py-8 text-center text-sm" style={{ color: 'var(--v-text-dim)' }}>Loading…</p>
          ) : sortedByLowest.length === 0 ? (
            <EmptyState
              headline="No stock configured"
              body="This bar has no bottles charged yet. Add one from the warehouse pool below."
            />
          ) : (
            <div>
              {sortedByLowest.map((r) => {
                const pct = Math.max(0, Math.min(100, r.remaining_pct))
                const color = STATUS_COLOR[isStockStatus(r.status) ? r.status : 'healthy']
                return (
                  <div key={r.supplier_product_id} className="py-3.5" style={{ borderBottom: '0.5px solid var(--v-border)' }}>
                    <div className="flex items-start justify-between gap-4 mb-2">
                      <span className="text-sm font-medium" style={{ color: 'var(--v-text)' }}>
                        {r.item_name}
                      </span>
                      <span className="shrink-0 text-sm font-medium tabular-nums" style={{ color }}>
                        {Math.round(pct)}%
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: 'var(--v-surface)' }}>
                      <div className="h-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
                    </div>
                    <p className="mt-1.5 text-xs tabular-nums" style={{ color: 'var(--v-text-dim)' }}>
                      {Math.round(r.remaining_ml).toLocaleString()} / {Math.round(r.dispatched_ml).toLocaleString()} ml remaining
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer — fixed */}
        <footer className="shrink-0 px-6 py-4" style={{ borderTop: '0.5px solid var(--v-border)' }}>
          <Button variant="primary" onClick={onAddBottle} className="w-full">
            + Add bottle
          </Button>
        </footer>
      </div>
    </div>
  )
}

// ─── Add bottle modal ────────────────────────────────────────────────

function AddBottleModal({
  bar, pickerRows, dispatchMut, onClose, onSuccess,
}: {
  bar: BarRow
  pickerRows: PickerRow[]
  dispatchMut: ReturnType<typeof useChargeBarDispatch>
  onClose: () => void
  onSuccess: (msg: string) => void
}) {
  const [selectedKey, setSelectedKey] = useState('')
  const [qty, setQty] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEscapeToClose(onClose)

  const selected = pickerRows.find((r) => r.key === selectedKey)
  const maxQty = selected ? Number(selected.remaining_qty) : 0

  const onConfirm = async () => {
    setError(null)
    const n = Number(qty)
    if (!selected || !selected.supplier_product_id) { setError('Pick an item.'); return }
    if (!Number.isFinite(n) || n <= 0) { setError('Qty must be > 0.'); return }
    if (n > maxQty) { setError(`Only ${maxQty} available.`); return }
    try {
      await dispatchMut.mutateAsync({
        supplier_product_id: selected.supplier_product_id,
        bar_id: bar.id,
        qty_allocated: String(n),
      })
      onSuccess(`Charged ${n} ${selected.unit} of ${selected.product_name} to ${bar.name}.`)
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Dispatch failed.')
    }
  }

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={MODAL_BACKDROP_STYLE}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl p-6"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-lg font-medium" style={{ color: 'var(--v-text)' }}>Add bottle — {bar.name}</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--v-text-muted)' }}>Charge from the warehouse pool</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 transition-colors"
            style={{ color: 'var(--v-text-dim)' }}
          >
            ✕
          </button>
        </div>

        {pickerRows.length === 0 ? (
          <p className="text-sm rounded-[var(--v-radius)] px-3 py-2" style={{ background: 'rgba(255, 216, 77, 0.08)', border: '0.5px solid var(--v-amber)', color: 'var(--v-amber)' }}>
            No products with remaining warehouse stock for this event.
          </p>
        ) : (
          <div className="space-y-3">
            <div>
              <Label>Item</Label>
              <select
                value={selectedKey}
                onChange={(e) => { setSelectedKey(e.target.value); setQty(''); setError(null) }}
                className={inputCls}
              >
                <option value="">— pick item —</option>
                {pickerRows.map((r) => (
                  <option key={r.key} value={r.key} disabled={r.supplier_product_id === null}>
                    {r.product_name} ({fmtQty(r.remaining_qty)}{r.unit ? ` ${r.unit}` : ''} remaining)
                    {r.supplier_product_id === null ? ' — not dispatchable' : ''}
                  </option>
                ))}
              </select>
            </div>

            {selected && selected.supplier_product_id === null && (
              <p className="text-xs" style={{ color: 'var(--v-amber)' }}>
                No matching warehouse dispatch item found for "{selected.product_name}" — can't be charged from here.
              </p>
            )}
            <p className="text-[11px]" style={{ color: 'var(--v-text-dim)' }}>
              Quantities are as invoiced — verify against physical units before confirming a large dispatch.
            </p>

            <div>
              <Label>Quantity</Label>
              <input
                type="number"
                min={0}
                max={maxQty || undefined}
                step={1}
                value={qty}
                onChange={(e) => { setQty(e.target.value); setError(null) }}
                placeholder={selected ? `qty (max ${maxQty})` : 'qty'}
                disabled={!selected || selected.supplier_product_id === null}
                className={inputCls}
              />
            </div>

            {error && <p className="text-xs" style={{ color: 'var(--v-pink)' }}>{error}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button
                variant="primary"
                onClick={onConfirm}
                disabled={dispatchMut.isPending || !selected || selected.supplier_product_id === null || !qty}
              >
                {dispatchMut.isPending ? 'Confirming…' : 'Confirm'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
