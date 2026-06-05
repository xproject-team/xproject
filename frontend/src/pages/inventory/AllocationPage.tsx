/**
 * AllocationPage — Phase C1 (Sundance 1 manual inventory mode).
 *
 * Editable grid: products (rows) x bars (columns) for a chosen event.
 * Each cell is the TARGET allocated_qty for that (bar, product). Edits
 * are tracked locally; Save posts only the changed cells via
 * POST /bar-stock/bulk-allocate (mode='set', idempotent, all-or-nothing).
 *
 * This is the warehouse-handoff page: Omar enters starting bottle counts
 * per bar before the event goes LIVE. QR-based flow comes in Sundance 2.
 */
import { useMemo, useState } from 'react'

import { useEvents } from '@/features/events/hooks'
import {
  useAllProducts,
  useBarsForEvent,
  useBarStockForEvent,
} from '@/features/dashboard/hooks'
import {
  useBulkAllocate,
  type BulkAllocateItemError,
} from '@/features/inventory/useBulkAllocate'

type Bar = { id: string; name: string; is_active?: boolean; bar_type?: string }
type Product = { id: string; name: string; category?: string; is_archived?: boolean }
type StockRow = { bar_id: string; product_id: string; allocated_qty: number }
type EventRow = { id: string; name: string; status: string }

const cellKey = (barId: string, productId: string) => `${barId}|${productId}`

export default function AllocationPage() {
  const eventsQ = useEvents()
  const events = ((eventsQ.data ?? []) as EventRow[]).filter(
    (e) => e.status !== 'COMPLETED' && e.status !== 'completed',
  )

  const [eventId, setEventId] = useState<string | null>(null)
  const effectiveEventId =
    eventId ??
    events.find((e) => e.status === 'LIVE' || e.status === 'live')?.id ??
    events[0]?.id ??
    null

  const barsQ = useBarsForEvent(effectiveEventId)
  const stockQ = useBarStockForEvent(effectiveEventId)
  const productsQ = useAllProducts()
  const bulk = useBulkAllocate()

  const bars = ((barsQ.data ?? []) as Bar[]).filter((b) => b.is_active !== false)
  const products = ((productsQ.data ?? []) as Product[]).filter(
    (p) => p.is_archived !== true,
  )
  const stock = (stockQ.data ?? []) as StockRow[]

  // Baseline allocated_qty per cell, from current bar_stock rows
  const baseline = useMemo(() => {
    const m = new Map<string, number>()
    for (const row of stock) {
      m.set(cellKey(row.bar_id, row.product_id), Number(row.allocated_qty))
    }
    return m
  }, [stock])

  const [edits, setEdits] = useState<Record<string, number>>({})
  const [search, setSearch] = useState('')
  const [banner, setBanner] = useState<string | null>(null)
  const [itemErrors, setItemErrors] = useState<BulkAllocateItemError[]>([])

  const visibleProducts = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (q === '') return products
    return products.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.category ?? '').toLowerCase().includes(q),
    )
  }, [products, search])

  const dirtyCells = useMemo(
    () =>
      Object.entries(edits).filter(
        ([key, val]) => val !== (baseline.get(key) ?? 0),
      ),
    [edits, baseline],
  )

  const cellValue = (barId: string, productId: string): number => {
    const key = cellKey(barId, productId)
    return edits[key] ?? baseline.get(key) ?? 0
  }

  const setCell = (barId: string, productId: string, raw: string) => {
    const n = Math.max(0, Math.floor(Number(raw) || 0))
    setEdits((prev) => ({ ...prev, [cellKey(barId, productId)]: n }))
  }

  const barName = (id: string) => bars.find((b) => b.id === id)?.name ?? id
  const productName = (id: string) =>
    products.find((p) => p.id === id)?.name ?? id

  const onSave = () => {
    if (effectiveEventId === null || dirtyCells.length === 0) return
    setBanner(null)
    setItemErrors([])
    const items = dirtyCells.map(([key, qty]) => {
      const [bar_id, product_id] = key.split('|')
      return { bar_id, product_id, qty }
    })
    bulk.mutate(
      { event_id: effectiveEventId, mode: 'set', items },
      {
        onSuccess: (res) => {
          setEdits({})
          setBanner(
            `Saved — ${res.created} created, ${res.updated} updated, ${res.unchanged} unchanged`,
          )
        },
        onError: (err: unknown) => {
          const detail = (err as {
            response?: { data?: { detail?: { error?: string; items?: BulkAllocateItemError[] } } }
          })?.response?.data?.detail
          if (detail?.error === 'bulk_validation_failed' && detail.items) {
            setItemErrors(detail.items)
            setBanner('Nothing saved — fix the items below and retry (all-or-nothing).')
          } else {
            setBanner('Save failed — check the backend logs.')
          }
        },
      },
    )
  }

  const loading = barsQ.isLoading || stockQ.isLoading || productsQ.isLoading

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-[#1A202C]">
          Inventory Allocation
        </h1>
        <span className="text-sm text-[#718096]">
          Starting bottle counts per bar (warehouse handoff)
        </span>
        <div className="ml-auto flex items-center gap-3">
          <select
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white"
            value={effectiveEventId ?? ''}
            onChange={(e) => {
              setEventId(e.target.value)
              setEdits({})
              setBanner(null)
              setItemErrors([])
            }}
          >
            {events.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name} ({e.status})
              </option>
            ))}
          </select>
          <button
            onClick={onSave}
            disabled={dirtyCells.length === 0 || bulk.isPending}
            className="px-4 py-1.5 rounded-md text-sm font-medium text-white bg-[#3182CE] disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            {bulk.isPending
              ? 'Saving…'
              : `Save ${dirtyCells.length > 0 ? `(${dirtyCells.length})` : ''}`}
          </button>
        </div>
      </div>

      {/* Banner + per-item errors */}
      {banner !== null && (
        <div
          className={`rounded-md px-4 py-2 text-sm ${
            itemErrors.length > 0
              ? 'bg-red-50 text-[#E53E3E] border border-red-200'
              : 'bg-green-50 text-[#38A169] border border-green-200'
          }`}
        >
          {banner}
          {itemErrors.length > 0 && (
            <ul className="mt-1 list-disc list-inside">
              {itemErrors.map((it) => (
                <li key={`${it.index}-${it.bar_id}-${it.product_id}`}>
                  {productName(it.product_id)} @ {barName(it.bar_id)}: {it.error}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Search */}
      <input
        type="text"
        placeholder="Filter products…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-64"
      />

      {/* Grid */}
      {loading ? (
        <div className="text-sm text-[#718096] py-8">Loading grid…</div>
      ) : bars.length === 0 ? (
        <div className="text-sm text-[#718096] py-8">
          No active bars for this event yet — add bars first.
        </div>
      ) : (
        <div className="overflow-x-auto border border-gray-200 rounded-lg">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="sticky left-0 bg-gray-50 px-3 py-2 text-left font-medium text-[#4A5568] border-b border-gray-200 min-w-[220px]">
                  Product
                </th>
                {bars.map((b) => (
                  <th
                    key={b.id}
                    className="px-2 py-2 text-center font-medium text-[#4A5568] border-b border-gray-200 whitespace-nowrap"
                  >
                    {b.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleProducts.map((p) => (
                <tr key={p.id} className="odd:bg-white even:bg-gray-50/50">
                  <td className="sticky left-0 bg-inherit px-3 py-1.5 border-b border-gray-100">
                    <span className="text-[#1A202C]">{p.name}</span>
                    {p.category !== undefined && (
                      <span className="ml-2 text-xs text-[#718096]">
                        {p.category}
                      </span>
                    )}
                  </td>
                  {bars.map((b) => {
                    const key = cellKey(b.id, p.id)
                    const dirty =
                      edits[key] !== undefined &&
                      edits[key] !== (baseline.get(key) ?? 0)
                    return (
                      <td
                        key={key}
                        className="px-2 py-1 border-b border-gray-100 text-center"
                      >
                        <input
                          type="number"
                          min={0}
                          value={cellValue(b.id, p.id)}
                          onChange={(e) => setCell(b.id, p.id, e.target.value)}
                          className={`w-16 text-center border rounded px-1 py-0.5 ${
                            dirty
                              ? 'border-[#3182CE] bg-blue-50'
                              : 'border-gray-200 bg-white'
                          }`}
                        />
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
