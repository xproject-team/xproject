/**
 * AllocationPage — Phase C1 (Sundance 1 manual inventory mode).
 *
 * Design-system conversion (Day 11 Phase 3): same editable grid, same
 * paste-from-Excel flow, same POST /bar-stock/bulk-allocate save — UI-only
 * restyle onto the dark design system used by Events/Bars/Catalog. No
 * hook, type, or backend change.
 *
 * Deliberately still has NO navigation link anywhere (URL-only,
 * /inventory/allocate) — per Day 11's investigation, giving this page
 * proper nav reachability is a separate product decision, not part of
 * this visual conversion.
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
import { Button, EmptyState, PageHeader } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label } from '@/design-system/wizardForm'

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
  const [showPaste, setShowPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteReport, setPasteReport] = useState<string | null>(null)

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

  /** C3 — parse a pasted Excel/CSV matrix and apply it as dirty grid edits.
   *  Expected shape (same as the grid):
   *    row 1:  <anything> | Bar Name | Bar Name | ...
   *    rows:   Product Name | qty | qty | ...
   *  Matching is by name, case-insensitive. Nothing is saved here — matched
   *  cells become dirty edits, reviewed and saved with the normal Save button.
   */
  const applyPaste = () => {
    const text = pasteText.trim()
    if (text === '') return
    const delim = text.includes('\t') ? '\t' : text.includes(';') ? ';' : ','
    const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '')
    if (lines.length < 2) {
      setPasteReport('Need a header row of bar names plus at least one product row.')
      return
    }

    const norm = (x: string) => x.trim().toLowerCase()
    const barByName = new Map(bars.map((b) => [norm(b.name), b.id]))
    const productByName = new Map(products.map((pr) => [norm(pr.name), pr.id]))

    const header = lines[0].split(delim)
    const colBarIds: Array<string | null> = header.map((h, i) =>
      i === 0 ? null : barByName.get(norm(h)) ?? null,
    )
    const unknownBars = header
      .slice(1)
      .filter((h, i) => h.trim() !== '' && colBarIds[i + 1] === null)

    let matched = 0
    const unknownProducts: string[] = []
    const badCells: string[] = []
    const newEdits: Record<string, number> = {}

    for (const line of lines.slice(1)) {
      const cells = line.split(delim)
      const pname = cells[0] ?? ''
      const productId = productByName.get(norm(pname)) ?? null
      if (productId === null) {
        if (pname.trim() !== '') unknownProducts.push(pname.trim())
        continue
      }
      for (let c = 1; c < cells.length; c++) {
        const barId = colBarIds[c]
        if (barId === null || barId === undefined) continue
        const raw = cells[c].trim()
        if (raw === '') continue
        const n = Math.floor(Number(raw))
        if (Number.isNaN(n) || n < 0) {
          badCells.push(`${pname.trim()} / ${header[c].trim()}: "${raw}"`)
          continue
        }
        newEdits[cellKey(barId, productId)] = n
        matched++
      }
    }

    setEdits((prev) => ({ ...prev, ...newEdits }))
    const parts = [`Applied ${matched} cell(s) to the grid — review and press Save.`]
    if (unknownBars.length > 0) parts.push(`Unknown bars skipped: ${unknownBars.join(', ')}.`)
    if (unknownProducts.length > 0) parts.push(`Unknown products skipped: ${unknownProducts.join(', ')}.`)
    if (badCells.length > 0) parts.push(`Invalid quantities skipped: ${badCells.join('; ')}.`)
    setPasteReport(parts.join(' '))
  }

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
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Inventory Allocation"
          subtitle="Starting bottle counts per bar (warehouse handoff)"
          actions={
            <div className="flex items-center gap-3">
              <select
                value={effectiveEventId ?? ''}
                onChange={(e) => {
                  setEventId(e.target.value)
                  setEdits({})
                  setBanner(null)
                  setItemErrors([])
                }}
                className={`${inputCls} w-56`}
              >
                {events.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name} ({e.status})
                  </option>
                ))}
              </select>
              <Button
                variant="primary"
                onClick={onSave}
                disabled={dirtyCells.length === 0 || bulk.isPending}
              >
                {bulk.isPending ? 'Saving…' : `Save${dirtyCells.length > 0 ? ` (${dirtyCells.length})` : ''}`}
              </Button>
            </div>
          }
        />
      </div>

      {/* Banner + per-item errors */}
      {banner !== null && (
        <div
          className="rounded-[var(--v-radius)] px-4 py-2.5 text-sm mb-4"
          style={
            itemErrors.length > 0
              ? { background: 'rgba(255, 61, 113, 0.08)', border: '0.5px solid var(--v-pink)', color: 'var(--v-pink)' }
              : { background: 'rgba(61, 255, 163, 0.08)', border: '0.5px solid var(--v-green)', color: 'var(--v-green)' }
          }
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
      <div className="mb-4 max-w-xs">
        <Label>Filter products</Label>
        <input
          type="text"
          placeholder="Filter products…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={inputCls}
        />
      </div>

      {/* C3 — Excel/CSV paste-in */}
      <div className="mb-4">
        <button
          onClick={() => setShowPaste((v) => !v)}
          className="text-sm"
          style={{ color: 'var(--v-cyan)' }}
        >
          {showPaste ? 'Hide paste panel' : 'Paste from Excel…'}
        </button>
        {showPaste && (
          <div
            className="mt-2 space-y-2 p-3"
            style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}
          >
            <p className="text-xs" style={{ color: 'var(--v-text-muted)' }}>
              Copy a range from Excel and paste it here. First row: bar names.
              First column: product names. Cells: quantities. Names must match
              the grid (case-insensitive). Nothing is saved until you press
              Save.
            </p>
            <textarea
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              rows={6}
              placeholder={'\tMain Bar\tBeer Bar\nGin Bombay 1L\t24\t0\nVodka Grey Goose 1L\t12\t6'}
              className={`${inputCls} font-mono`}
            />
            <div className="flex items-center gap-3">
              <Button variant="secondary" onClick={applyPaste}>Apply to grid</Button>
              {pasteReport !== null && (
                <span className="text-xs" style={{ color: 'var(--v-text-muted)' }}>{pasteReport}</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Grid */}
      {loading ? (
        <div className="py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
          <div className="inline-flex items-center gap-2">
            <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
            Loading grid…
          </div>
        </div>
      ) : bars.length === 0 ? (
        <EmptyState headline="No active bars for this event" body="Add bars to this event before allocating starting stock." />
      ) : (
        <div
          className="overflow-x-auto"
          style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
        >
          <table className="min-w-full text-sm">
            <thead>
              <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
                <th
                  className="sticky left-0 px-4 py-3 text-left text-[10px] font-bold uppercase tracking-[0.06em] min-w-[220px]"
                  style={{ background: 'var(--v-surface-raised)', color: 'var(--v-text-muted)' }}
                >
                  Product
                </th>
                {bars.map((b) => (
                  <th
                    key={b.id}
                    className="px-2 py-3 text-center text-[10px] font-bold uppercase tracking-[0.06em] whitespace-nowrap"
                    style={{ color: 'var(--v-text-muted)' }}
                  >
                    {b.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleProducts.length === 0 ? (
                <tr>
                  <td colSpan={1 + bars.length} className="px-5 py-12">
                    <EmptyState headline="No products match" body="Try a different filter." />
                  </td>
                </tr>
              ) : visibleProducts.map((p) => (
                <tr
                  key={p.id}
                  className="transition-colors last:border-0"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="sticky left-0 px-4 py-2" style={{ background: 'var(--v-surface)' }}>
                    <span style={{ color: 'var(--v-text)' }}>{p.name}</span>
                    {p.category !== undefined && (
                      <span className="ml-2 text-xs" style={{ color: 'var(--v-text-dim)' }}>
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
                      <td key={key} className="px-2 py-1.5 text-center">
                        <input
                          type="number"
                          min={0}
                          value={cellValue(b.id, p.id)}
                          onChange={(e) => setCell(b.id, p.id, e.target.value)}
                          className="w-16 text-center rounded-[var(--v-radius-sm)] px-1 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--v-cyan)]/30 focus:border-[var(--v-cyan)] transition-colors"
                          style={{
                            background: dirty ? 'rgba(0, 229, 212, 0.08)' : 'var(--v-bg-base)',
                            border: `0.5px solid ${dirty ? 'var(--v-cyan)' : 'var(--v-border)'}`,
                            color: 'var(--v-text)',
                          }}
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
