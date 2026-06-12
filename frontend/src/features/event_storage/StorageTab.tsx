/**
 * StorageTab — wizard step 7 of the Create/Edit Event flow.
 *
 * Lets Omar declare every bottle bought for the event from the supplier
 * master list. Each row: pick item -> set qty -> price prefills from
 * last_unit_price. Save calls /event-storage/items/bulk.
 *
 * EDIT MODE ONLY in v1: event_stock_items.event_id is FK to events.id
 * with CASCADE, so the event must exist. Pre-save we show a soft hint.
 */
import { useEffect, useMemo, useState } from 'react'

import {
  useBulkUpsertEventStockItems,
  useDeleteEventStockItem,
  useEventStockItems,
  useSupplierProducts,
} from './hooks'

import type { EventStockItemCreate, SupplierProduct } from './types'


interface EditableRow {
  serverId: string | undefined
  supplierProductId: string
  itemName: string
  category: string
  unit: string
  qty: string
  unitPrice: string
}

const inputCls =
  'rounded-lg border border-[#E2E8F0] px-2 py-1 text-sm text-[#1A202C] focus:outline-none focus:ring-2 focus:ring-[#3182CE]/30 focus:border-[#3182CE]'

const CATEGORY_LABELS: Record<string, string> = {
  gin: 'Gin',
  vodka: 'Vodka',
  whiskey: 'Whiskey',
  rum: 'Rum',
  tequila: 'Tequila',
  mezcal: 'Mezcal',
  aperitivo: 'Aperitivi & Liquori',
  premix: 'Pre-mix',
  beer_keg: 'Beer (keg)',
  sparkling: 'Sparkling wine',
  mixer: 'Mixers',
  soft_drink: 'Soft drinks',
  juice: 'Juice',
  water_still: 'Water (still)',
  water_sparkling: 'Water (sparkling)',
  equipment: 'Equipment',
}
const categoryLabel = (cat: string) => CATEGORY_LABELS[cat] ?? cat


function parseAmount(s: string): number {
  const n = Number(String(s).replace(',', '.').trim())
  return Number.isFinite(n) ? n : 0
}

function lineTotal(row: EditableRow): number {
  return parseAmount(row.qty) * parseAmount(row.unitPrice)
}


export default function StorageTab({ eventId }: { eventId: string | undefined }) {
  if (!eventId) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
        <p className="font-semibold mb-1">Save the event first</p>
        <p>
          Storage rows attach to the event, so click <strong>Save Draft</strong> at
          the top of any earlier tab to create the event. Then come back here
          to declare your bottles, kegs, and canisters.
        </p>
      </div>
    )
  }

  const supplierQ = useSupplierProducts()
  const itemsQ = useEventStockItems(eventId)
  const bulkUpsert = useBulkUpsertEventStockItems(eventId)
  const deleteItem = useDeleteEventStockItem(eventId)

  const [rows, setRows] = useState<EditableRow[]>([])
  const [picking, setPicking] = useState(false)
  const [pickerCategory, setPickerCategory] = useState<string>('')
  const [banner, setBanner] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  // Hydrate local state when server items load. We keep a derived map of
  // supplier product details so each row carries its name + unit + category
  // for display.
  const supplierById = useMemo(() => {
    const m = new Map<string, SupplierProduct>()
    for (const sp of supplierQ.data ?? []) m.set(sp.id, sp)
    return m
  }, [supplierQ.data])

  useEffect(() => {
    if (!itemsQ.data || !supplierQ.data) return
    const mapped: EditableRow[] = itemsQ.data.map(it => {
      const sp = supplierById.get(it.supplier_product_id)
      return {
        serverId: it.id,
        supplierProductId: it.supplier_product_id,
        itemName: sp?.item_name ?? '(unknown item)',
        category: sp?.category ?? 'other',
        unit: it.unit,
        qty: it.qty_received,
        unitPrice: it.unit_price_eur ?? '',
      }
    })
    setRows(mapped)
  }, [itemsQ.data, supplierById, supplierQ.data])

  // Sort rows by category, then by item name, so visually grouped.
  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const c = a.category.localeCompare(b.category)
      return c !== 0 ? c : a.itemName.localeCompare(b.itemName)
    })
  }, [rows])

  const totals = useMemo(() => {
    const totalItems = rows.length
    const totalQty = rows.reduce((s, r) => s + parseAmount(r.qty), 0)
    const totalEur = rows.reduce((s, r) => s + lineTotal(r), 0)
    return { totalItems, totalQty, totalEur }
  }, [rows])

  // Master list filtered by category + excluding already-added items
  const addableProducts = useMemo(() => {
    if (!supplierQ.data) return []
    const alreadyAdded = new Set(rows.map(r => r.supplierProductId))
    return supplierQ.data
      .filter(sp => !alreadyAdded.has(sp.id))
      .filter(sp => !pickerCategory || sp.category === pickerCategory)
      .sort((a, b) => a.item_name.localeCompare(b.item_name))
  }, [supplierQ.data, rows, pickerCategory])

  const categoryOptions = useMemo(() => {
    if (!supplierQ.data) return [] as string[]
    return Array.from(new Set(supplierQ.data.map(sp => sp.category))).sort()
  }, [supplierQ.data])

  function addRow(sp: SupplierProduct) {
    setRows(prev => [
      ...prev,
      {
        serverId: undefined,
        supplierProductId: sp.id,
        itemName: sp.item_name,
        category: sp.category,
        unit: sp.default_unit,
        qty: '1',
        unitPrice: sp.last_unit_price_eur ?? '',
      },
    ])
    setPicking(false)
  }

  async function removeRow(row: EditableRow) {
    if (row.serverId) {
      try {
        await deleteItem.mutateAsync(row.serverId)
      } catch (e) {
        setBanner({ kind: 'err', text: 'Failed to delete row from server.' })
        return
      }
    }
    setRows(prev => prev.filter(r => r.supplierProductId !== row.supplierProductId))
  }

  function updateRow(supplierProductId: string, patch: Partial<EditableRow>) {
    setRows(prev =>
      prev.map(r =>
        r.supplierProductId === supplierProductId ? { ...r, ...patch } : r,
      ),
    )
  }

  async function saveAll() {
    setBanner(null)
    const payload: EventStockItemCreate[] = rows.map(r => ({
      supplier_product_id: r.supplierProductId,
      qty_received: r.qty || '0',
      unit: r.unit,
      unit_price_eur: r.unitPrice || null,
      line_total_eur: lineTotal(r).toFixed(2),
    }))
    try {
      await bulkUpsert.mutateAsync(payload)
      setBanner({ kind: 'ok', text: `Saved ${payload.length} item(s).` })
    } catch (e) {
      setBanner({ kind: 'err', text: 'Save failed — check the rows and retry.' })
    }
  }

  if (supplierQ.isLoading || itemsQ.isLoading) {
    return <div className="text-sm text-[#4A5568]">Loading storage…</div>
  }

  // Render groups: split sortedRows by category for visual headers
  const groups: Array<{ category: string; items: EditableRow[] }> = []
  let cur: { category: string; items: EditableRow[] } | null = null
  for (const r of sortedRows) {
    if (!cur || cur.category !== r.category) {
      cur = { category: r.category, items: [] }
      groups.push(cur)
    }
    cur.items.push(r)
  }

  return (
    <div className="space-y-4">
      {banner && (
        <div
          className={`rounded-lg p-3 text-sm ${
            banner.kind === 'ok'
              ? 'bg-emerald-50 border border-emerald-300 text-emerald-900'
              : 'bg-red-50 border border-red-300 text-red-900'
          }`}
        >
          {banner.text}
        </div>
      )}

      {/* Totals */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-[#4A5568]">
        <span><strong className="text-[#1A202C]">{totals.totalItems}</strong> items</span>
        <span><strong className="text-[#1A202C]">{totals.totalQty.toFixed(0)}</strong> units total</span>
        <span><strong className="text-[#1A202C]">€{totals.totalEur.toFixed(2)}</strong> total value</span>
      </div>

      {/* Add control */}
      <div className="rounded-lg border border-[#E2E8F0] bg-white p-3">
        {!picking ? (
          <button
            type="button"
            onClick={() => setPicking(true)}
            className="rounded-lg bg-[#3182CE] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2C5282]"
          >
            + Add item from catalog
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex gap-2 items-center">
              <select
                className={inputCls}
                value={pickerCategory}
                onChange={e => setPickerCategory(e.target.value)}
              >
                <option value="">All categories</option>
                {categoryOptions.map(c => (
                  <option key={c} value={c}>{categoryLabel(c)}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setPicking(false)}
                className="text-sm text-[#718096] hover:text-[#1A202C]"
              >
                Cancel
              </button>
            </div>
            <div className="max-h-72 overflow-y-auto rounded border border-[#E2E8F0]">
              {addableProducts.length === 0 ? (
                <div className="p-3 text-sm text-[#718096]">
                  No items available in this category (or all already added).
                </div>
              ) : (
                <ul className="divide-y divide-[#E2E8F0]">
                  {addableProducts.map(sp => (
                    <li key={sp.id}>
                      <button
                        type="button"
                        onClick={() => addRow(sp)}
                        className="w-full text-left px-3 py-2 hover:bg-[#F7FAFC] text-sm"
                      >
                        <div className="flex justify-between gap-3">
                          <span className="font-medium text-[#1A202C]">{sp.item_name}</span>
                          <span className="text-[#718096] text-xs">
                            {sp.default_unit} · €{sp.last_unit_price_eur ?? '—'}
                          </span>
                        </div>
                        <div className="text-xs text-[#718096]">
                          {categoryLabel(sp.category)} · SKU {sp.supplier_sku}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Rows table — grouped by category */}
      {groups.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#CBD5E0] bg-[#F7FAFC] p-6 text-center text-sm text-[#718096]">
          No stock declared yet. Click <strong>+ Add item</strong> to start.
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map(group => (
            <div
              key={group.category}
              className="rounded-lg border border-[#E2E8F0] bg-white overflow-hidden"
            >
              <div className="bg-[#F7FAFC] px-3 py-2 text-xs font-semibold uppercase tracking-wide text-[#4A5568]">
                {categoryLabel(group.category)} · {group.items.length} item{group.items.length === 1 ? '' : 's'}
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs font-semibold text-[#718096] border-b border-[#E2E8F0]">
                    <th className="px-3 py-2">Item</th>
                    <th className="px-3 py-2 w-20">Qty</th>
                    <th className="px-3 py-2 w-20">Unit</th>
                    <th className="px-3 py-2 w-28">Unit € (list)</th>
                    <th className="px-3 py-2 w-28">Line total</th>
                    <th className="px-3 py-2 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {group.items.map(row => (
                    <tr key={row.supplierProductId} className="border-b border-[#F1F5F9] last:border-b-0">
                      <td className="px-3 py-2 text-[#1A202C]">{row.itemName}</td>
                      <td className="px-3 py-2">
                        <input
                          className={`${inputCls} w-16`}
                          inputMode="decimal"
                          value={row.qty}
                          onChange={e => updateRow(row.supplierProductId, { qty: e.target.value })}
                        />
                      </td>
                      <td className="px-3 py-2 text-[#4A5568]">{row.unit}</td>
                      <td className="px-3 py-2">
                        <input
                          className={`${inputCls} w-24`}
                          inputMode="decimal"
                          value={row.unitPrice}
                          onChange={e => updateRow(row.supplierProductId, { unitPrice: e.target.value })}
                        />
                      </td>
                      <td className="px-3 py-2 text-[#1A202C] tabular-nums">
                        €{lineTotal(row).toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => removeRow(row)}
                          className="text-[#A0AEC0] hover:text-red-600 px-1"
                          aria-label="Remove row"
                          title="Remove row"
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Save */}
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={saveAll}
          disabled={bulkUpsert.isPending || rows.length === 0}
          className="rounded-lg bg-[#48BB78] px-5 py-2 text-sm font-semibold text-white hover:bg-[#2F855A] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {bulkUpsert.isPending ? 'Saving…' : 'Save storage'}
        </button>
      </div>
    </div>
  )
}
