/**
 * EventCreatePage — Slesh-aligned Create/Edit Event wizard (Phase D).
 *
 * Seven tabs mirroring Omar's Slesh planning Excel:
 *   1 Overview   2 Parametri   3 Bars   4 Device Count
 *   5 Listini    6 Inventory   7 Lineup (stub)
 *
 * Create mode (no :id): POST /events/full.
 * Edit mode (/events/:id/edit, DRAFT only): hydrates from the event's
 * bars + menu (event_products) + allocations (bar_stock), and saves via
 * PUT /events/{id}/full (replace semantics). State is page-level so tab
 * switches never lose input; a 422 jumps to the offending tab.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { getApiError, useEvent } from '@/features/events/hooks'
import { useVenues } from '@/features/venues/hooks'
import { useAllProducts, useBarsForEvent, useBarStockForEvent } from '@/features/dashboard/hooks'
import {
  useCreateFullEvent,
  useUpdateFullEvent,
  extractFullEventErrors,
  type FullEventCreatePayload,
  type FullEventItemError,
} from '@/features/events/useCreateFullEvent'

interface BarRow {
  id: number
  name: string
  slesh_negozio_id: string
  bar_type: 'drinks' | 'food'
  slesh_category: string
  device_count: number
}
interface ListiniRow {
  id: number
  bar_id: number | null
  name: string
  product_type: 'drink' | 'food'
  category: string
  unit: string
  price: string
  iva: string
  cauzione: string
}
interface WristbandRow {
  id: number
  label: string
  qty: number
}

const TABS = ['1 · Overview', '2 · Parametri', '3 · Bars', '4 · Device Count', '5 · Listini', '6 · Inventory', '7 · Lineup']

const inputCls =
  'w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#1A202C] focus:outline-none focus:ring-2 focus:ring-[#3182CE]/30 focus:border-[#3182CE]'

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-semibold text-[#4A5568] mb-1">{children}</label>
}

const eurosToCents = (s: string): number | null => {
  const n = Number(String(s).replace(',', '.').trim())
  if (String(s).trim() === '' || Number.isNaN(n) || n < 0) return null
  return Math.round(n * 100)
}
const csvEurosToCents = (s: string): number[] =>
  s.split(/[,;\s]+/).map((x) => x.trim()).filter((x) => x !== '')
    .map((x) => Math.round(Number(x.replace(',', '.')) * 100)).filter((n) => !Number.isNaN(n) && n >= 0)
const productKey = (name: string, type: string) => `${type}::${name.trim().toLowerCase()}`

export default function EventCreatePage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const editMode = Boolean(id)

  const { data: venues = [] } = useVenues()
  const createFull = useCreateFullEvent()
  const updateFull = useUpdateFullEvent()

  // Edit-mode data sources (disabled in create mode)
  const eventQ = useEvent(id)
  const barsQ = useBarsForEvent(id ?? null)
  const stockQ = useBarStockForEvent(id ?? null)
  const productsQ = useAllProducts()
  const menuQ = useQuery({
    queryKey: ['event-menu', id],
    queryFn: async () => (await api.get(`/event-products/by-event/${id}`)).data as Array<{ bar_id: string; product_id: string; price_cents: number }>,
    enabled: editMode,
  })

  const [tab, setTab] = useState(0)
  const [banner, setBanner] = useState<{ kind: 'error' | 'ok'; text: string } | null>(null)
  const [itemErrors, setItemErrors] = useState<FullEventItemError[]>([])

  const [name, setName] = useState('')
  const [venueId, setVenueId] = useState('')
  const [startAt, setStartAt] = useState('')
  const [endAt, setEndAt] = useState('')
  const [guests, setGuests] = useState('1600')
  const [staffArrival, setStaffArrival] = useState('11:00')
  const [stripeRagione, setStripeRagione] = useState('')
  const [wristbands, setWristbands] = useState<WristbandRow[]>([
    { id: 1, label: 'Tipo 1', qty: 1800 }, { id: 2, label: 'Tipo 2', qty: 1800 },
    { id: 3, label: 'Tipo 3', qty: 1800 }, { id: 4, label: 'Tipo 4', qty: 1800 },
  ])

  const [topupUser, setTopupUser] = useState('5, 10, 20, 50, 100')
  const [topupStaff, setTopupStaff] = useState('5')
  const [refundMin, setRefundMin] = useState('1')
  const [refundFee, setRefundFee] = useState('0.50')
  const [refundOpen, setRefundOpen] = useState('')
  const [refundClose, setRefundClose] = useState('')

  const [bars, setBars] = useState<BarRow[]>([])
  const [nextBarId, setNextBarId] = useState(1)
  const addBar = () => { setBars((p) => [...p, { id: nextBarId, name: '', slesh_negozio_id: '', bar_type: 'drinks', slesh_category: '', device_count: 0 }]); setNextBarId((n) => n + 1) }
  const updateBar = <K extends keyof BarRow>(rid: number, key: K, val: BarRow[K]) => setBars((p) => p.map((b) => (b.id === rid ? { ...b, [key]: val } : b)))
  const removeBar = (rid: number) => setBars((p) => p.filter((b) => b.id !== rid))

  const [listini, setListini] = useState<ListiniRow[]>([])
  const [nextListiniId, setNextListiniId] = useState(1)
  const addListini = () => { setListini((p) => [...p, { id: nextListiniId, bar_id: bars[0]?.id ?? null, name: '', product_type: 'drink', category: '', unit: 'bottle', price: '', iva: '10', cauzione: '' }]); setNextListiniId((n) => n + 1) }
  const updateListini = <K extends keyof ListiniRow>(rid: number, key: K, val: ListiniRow[K]) => setListini((p) => p.map((r) => (r.id === rid ? { ...r, [key]: val } : r)))
  const removeListini = (rid: number) => setListini((p) => p.filter((r) => r.id !== rid))

  const [alloc, setAlloc] = useState<Record<string, number>>({})

  // ── Edit-mode hydration (runs once when all sources are loaded) ──
  const hydrated = useRef(false)
  useEffect(() => {
    if (!editMode || hydrated.current) return
    const ev = eventQ.data as Record<string, unknown> | undefined
    const barsData = barsQ.data as Array<Record<string, unknown>> | undefined
    const productsData = productsQ.data as Array<Record<string, unknown>> | undefined
    const stockData = stockQ.data as Array<Record<string, unknown>> | undefined
    const menuData = menuQ.data
    if (!ev || !barsData || !productsData || !stockData || !menuData) return

    // Event scalar fields
    setName(String(ev.name ?? ''))
    const venue = ev.venue as { id?: string } | undefined
    setVenueId(venue?.id ?? '')
    setStartAt(String(ev.scheduled_at ?? '').slice(0, 16))
    setEndAt(String(ev.scheduled_end_at ?? '').slice(0, 16))
    setGuests(String(ev.expected_guest_count ?? ''))
    if (ev.staff_arrival_time) setStaffArrival(String(ev.staff_arrival_time).slice(0, 5))
    setStripeRagione(String(ev.stripe_ragione_sociale ?? ''))
    const wb = ev.wristband_qty_per_type as Record<string, number> | null
    if (wb && Object.keys(wb).length) setWristbands(Object.entries(wb).map(([label, qty], i) => ({ id: i + 1, label, qty: Number(qty) })))
    const tu = ev.topup_denominations_user as number[] | null
    if (tu) setTopupUser(tu.map((c) => c / 100).join(', '))
    const ts = ev.topup_denominations_staff as number[] | null
    if (ts) setTopupStaff(ts.map((c) => c / 100).join(', '))
    if (ev.refund_min_credit_cents != null) setRefundMin(String((ev.refund_min_credit_cents as number) / 100))
    if (ev.refund_fee_cents != null) setRefundFee(String((ev.refund_fee_cents as number) / 100))
    if (ev.refund_window_open_at) setRefundOpen(String(ev.refund_window_open_at).slice(0, 16))
    if (ev.refund_window_close_at) setRefundClose(String(ev.refund_window_close_at).slice(0, 16))

    // Bars → local rows + backend-id → local-id map
    const barIdMap = new Map<string, number>()
    const localBars: BarRow[] = barsData.map((b, i) => {
      barIdMap.set(String(b.id), i + 1)
      return {
        id: i + 1,
        name: String(b.name ?? ''),
        slesh_negozio_id: String(b.slesh_negozio_id ?? ''),
        bar_type: (b.bar_type === 'food' ? 'food' : 'drinks'),
        slesh_category: String(b.slesh_category ?? ''),
        device_count: Number(b.device_count ?? 0),
      }
    })
    setBars(localBars)
    setNextBarId(localBars.length + 1)

    // Product catalog lookup
    const catalog = new Map<string, Record<string, unknown>>()
    for (const p of productsData) catalog.set(String(p.id), p)

    // Listini rows from menu (event_products)
    const rows: ListiniRow[] = []
    menuData.forEach((m, i) => {
      const p = catalog.get(String(m.product_id))
      const localBar = barIdMap.get(String(m.bar_id)) ?? null
      const ptype: 'drink' | 'food' = p && p.product_type === 'food' ? 'food' : 'drink'
      rows.push({
        id: i + 1,
        bar_id: localBar,
        name: p ? String(p.name) : '',
        product_type: ptype,
        category: p && p.category ? String(p.category) : '',
        unit: p && p.unit ? String(p.unit) : 'bottle',
        price: (Number(m.price_cents) / 100).toString(),
        iva: p && p.iva_pct != null ? String((p.iva_pct as number) * 100) : '',
        cauzione: p && p.cauzione_cents != null ? String((p.cauzione_cents as number) / 100) : '',
      })
    })
    setListini(rows)
    setNextListiniId(rows.length + 1)

    // Allocations grid
    const a: Record<string, number> = {}
    for (const bs of stockData) {
      const p = catalog.get(String(bs.product_id))
      const localBar = barIdMap.get(String(bs.bar_id))
      if (!p || localBar === undefined) continue
      const ptype = p.product_type === 'food' ? 'food' : 'drink'
      a[`${localBar}|${productKey(String(p.name), ptype)}`] = Number(bs.allocated_qty)
    }
    setAlloc(a)

    hydrated.current = true
  }, [editMode, eventQ.data, barsQ.data, productsQ.data, stockQ.data, menuQ.data])

  const payloadBars = useMemo(() => bars.filter((b) => b.name.trim() !== ''), [bars])
  const uniqueProducts = useMemo(() => {
    const seen = new Map<string, { key: string; name: string; type: string }>()
    for (const r of listini) {
      if (r.name.trim() === '') continue
      const k = productKey(r.name, r.product_type)
      if (!seen.has(k)) seen.set(k, { key: k, name: r.name.trim(), type: r.product_type })
    }
    return [...seen.values()]
  }, [listini])

  function buildPayload(): { payload: FullEventCreatePayload | null; preErrors: string[] } {
    const preErrors: string[] = []
    if (name.trim() === '') preErrors.push('Overview: event name is required')
    if (venueId === '') preErrors.push('Overview: venue is required')
    if (startAt === '') preErrors.push('Overview: start time is required')
    if (endAt === '') preErrors.push('Overview: end time is required')
    if (startAt && endAt && new Date(endAt) <= new Date(startAt)) preErrors.push('Overview: end must be after start')
    if (payloadBars.length === 0) preErrors.push('Bars: add at least one bar with a name')
    const named = listini.filter((r) => r.name.trim() !== '')
    if (named.length === 0) preErrors.push('Listini: add at least one product')

    const barIndexById = new Map(payloadBars.map((b, i) => [b.id, i]))
    const productIndexByKey = new Map<string, number>()
    const products: FullEventCreatePayload['products'] = []
    const menu: FullEventCreatePayload['menu'] = []
    const menuPairs = new Set<string>()

    for (const r of named) {
      if (r.bar_id === null || !barIndexById.has(r.bar_id)) { preErrors.push(`Listini: "${r.name}" has no valid bar selected`); continue }
      const priceCents = eurosToCents(r.price)
      if (priceCents === null) { preErrors.push(`Listini: "${r.name}" has an invalid price`); continue }
      const bIndex = barIndexById.get(r.bar_id) as number
      const pk = productKey(r.name, r.product_type)
      let pIndex = productIndexByKey.get(pk)
      if (pIndex === undefined) {
        pIndex = products.length
        productIndexByKey.set(pk, pIndex)
        const ivaPct = r.iva.trim() === '' ? null : Number(r.iva) / 100
        products.push({ name: r.name.trim(), product_type: r.product_type, category: r.product_type === 'drink' ? (r.category.trim() || 'basic_cocktail') : null, unit: r.unit || 'bottle', default_price_cents: priceCents, iva_pct: ivaPct, cauzione_cents: eurosToCents(r.cauzione) })
      }
      const pairKey = `${bIndex}|${pIndex}`
      if (menuPairs.has(pairKey)) { preErrors.push(`Listini: "${r.name}" listed twice at the same bar`); continue }
      menuPairs.add(pairKey)
      menu.push({ bar_index: bIndex, product_index: pIndex, price_cents: priceCents, is_available: true })
    }

    const allocations: FullEventCreatePayload['allocations'] = []
    for (const [key, qty] of Object.entries(alloc)) {
      if (qty <= 0) continue
      const [barIdStr, pk] = key.split('|', 2)
      const bIndex = barIndexById.get(Number(barIdStr))
      const pIndex = productIndexByKey.get(pk)
      if (bIndex === undefined || pIndex === undefined) continue
      allocations.push({ bar_index: bIndex, product_index: pIndex, qty })
    }

    if (preErrors.length > 0) return { payload: null, preErrors }

    const wbObj: Record<string, number> = {}
    for (const w of wristbands) if (w.label.trim() !== '') wbObj[w.label.trim()] = w.qty

    const payload: FullEventCreatePayload = {
      event: {
        name: name.trim(), venue_id: venueId, scheduled_at: startAt, scheduled_end_at: endAt,
        expected_guest_count: Number(guests) || null,
        stripe_ragione_sociale: stripeRagione.trim() || null,
        staff_arrival_time: staffArrival.trim() || null,
        wristband_qty_per_type: Object.keys(wbObj).length ? wbObj : null,
        topup_denominations_user: csvEurosToCents(topupUser),
        topup_denominations_staff: csvEurosToCents(topupStaff),
        refund_min_credit_cents: eurosToCents(refundMin),
        refund_fee_cents: eurosToCents(refundFee),
        refund_window_open_at: refundOpen || null,
        refund_window_close_at: refundClose || null,
      },
      bars: payloadBars.map((b) => ({ name: b.name.trim(), slesh_negozio_id: b.slesh_negozio_id.trim() || null, bar_type: b.bar_type, device_count: b.device_count, slesh_category: b.slesh_category.trim() || null, is_active: true })),
      products, menu, allocations,
    }
    return { payload, preErrors: [] }
  }

  const SECTION_TAB: Record<string, number> = { bars: 2, products: 4, menu: 4, allocations: 5 }
  const saving = createFull.isPending || updateFull.isPending

  function onSave() {
    setBanner(null)
    setItemErrors([])
    const { payload, preErrors } = buildPayload()
    if (payload === null) { setBanner({ kind: 'error', text: preErrors.join(' · ') }); return }
    const onErr = (err: unknown) => {
      const items = extractFullEventErrors(err)
      if (items) {
        setItemErrors(items)
        setBanner({ kind: 'error', text: `Rejected — ${items.length} item(s) need fixing (nothing saved).` })
        if (items[0]) setTab(SECTION_TAB[items[0].section] ?? 0)
      } else {
        const apiErr = getApiError(err)
        setBanner({ kind: 'error', text: apiErr?.message ?? 'Save failed.' })
      }
    }
    if (editMode && id) {
      updateFull.mutate({ eventId: id, payload }, { onSuccess: () => navigate('/events'), onError: onErr })
    } else {
      createFull.mutate(payload, { onSuccess: () => navigate('/events'), onError: onErr })
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto pb-24">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">{editMode ? 'Edit Event' : 'Create Event'}</h1>
          <p className="text-sm text-[#4A5568] mt-1">{editMode ? 'Editing a draft — Save replaces the bars, menu, and allocations.' : 'Mirrors the Slesh planning sheet. Saved as a draft; activate from the event page.'}</p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/events')} className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]">Cancel</button>
          <button onClick={onSave} disabled={saving} className="text-sm font-semibold text-white px-4 py-2 rounded-lg disabled:bg-gray-300" style={{ backgroundColor: saving ? undefined : '#1ABC9C' }}>{saving ? 'Saving…' : editMode ? 'Save Changes' : 'Save Draft'}</button>
        </div>
      </div>

      {banner && (
        <div className={`rounded-lg px-4 py-2 text-sm mb-4 ${banner.kind === 'error' ? 'bg-red-50 text-[#E53E3E] border border-red-200' : 'bg-green-50 text-[#38A169] border border-green-200'}`}>
          {banner.text}
          {itemErrors.length > 0 && (<ul className="mt-1 list-disc list-inside">{itemErrors.map((it, i) => (<li key={i}>{it.section} #{it.index}: {it.error}</li>))}</ul>)}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-[#E2E8F0] mb-5">
        {TABS.map((t, i) => (<button key={t} onClick={() => setTab(i)} className={`px-3 py-2 text-sm font-medium rounded-t-lg ${tab === i ? 'text-[#3182CE] border-b-2 border-[#3182CE]' : 'text-[#718096] hover:text-[#4A5568]'}`}>{t}</button>))}
      </div>

      {tab === 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div><Label>Event Name</Label><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Sundance Sunday" /></div>
          <div><Label>Venue</Label><select className={`${inputCls} bg-white`} value={venueId} onChange={(e) => setVenueId(e.target.value)}><option value="">Select venue…</option>{venues.map((v: { id: string; name: string }) => (<option key={v.id} value={v.id}>{v.name}</option>))}</select></div>
          <div><Label>Start</Label><input type="datetime-local" className={inputCls} value={startAt} onChange={(e) => setStartAt(e.target.value)} /></div>
          <div><Label>End</Label><input type="datetime-local" className={inputCls} value={endAt} onChange={(e) => setEndAt(e.target.value)} /></div>
          <div><Label>Expected Guests</Label><input type="number" className={inputCls} value={guests} onChange={(e) => setGuests(e.target.value)} /></div>
          <div><Label>Staff Arrival Time</Label><input type="time" className={inputCls} value={staffArrival} onChange={(e) => setStaffArrival(e.target.value)} /></div>
          <div className="sm:col-span-2"><Label>Stripe — Ragione Sociale</Label><input className={inputCls} value={stripeRagione} onChange={(e) => setStripeRagione(e.target.value)} placeholder="Sundance srls" /></div>
          <div className="sm:col-span-2"><Label>Wristbands (label × quantity)</Label><div className="space-y-2">{wristbands.map((w) => (<div key={w.id} className="flex gap-2"><input className={`${inputCls} flex-1`} value={w.label} onChange={(e) => setWristbands((p) => p.map((x) => x.id === w.id ? { ...x, label: e.target.value } : x))} /><input type="number" className={`${inputCls} w-32`} value={w.qty} onChange={(e) => setWristbands((p) => p.map((x) => x.id === w.id ? { ...x, qty: Number(e.target.value) || 0 } : x))} /></div>))}</div></div>
        </div>
      )}

      {tab === 1 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div><Label>Top-up — User (€, comma-separated)</Label><input className={inputCls} value={topupUser} onChange={(e) => setTopupUser(e.target.value)} /></div>
          <div><Label>Top-up — Staff (€)</Label><input className={inputCls} value={topupStaff} onChange={(e) => setTopupStaff(e.target.value)} /></div>
          <div><Label>Refund — Min credit (€)</Label><input className={inputCls} value={refundMin} onChange={(e) => setRefundMin(e.target.value)} /></div>
          <div><Label>Refund — Handling fee (€)</Label><input className={inputCls} value={refundFee} onChange={(e) => setRefundFee(e.target.value)} /></div>
          <div><Label>Refund window — Opens</Label><input type="datetime-local" className={inputCls} value={refundOpen} onChange={(e) => setRefundOpen(e.target.value)} /></div>
          <div><Label>Refund window — Closes</Label><input type="datetime-local" className={inputCls} value={refundClose} onChange={(e) => setRefundClose(e.target.value)} /></div>
        </div>
      )}

      {tab === 2 && (
        <div>
          <button onClick={addBar} className="mb-3 text-sm font-semibold text-white px-3 py-1.5 rounded-lg bg-[#3182CE]">+ Add bar</button>
          <div className="space-y-2">
            {bars.map((b) => (<div key={b.id} className="flex flex-wrap gap-2 items-center">
              <input className={`${inputCls} flex-1 min-w-[160px]`} placeholder="Bar name" value={b.name} onChange={(e) => updateBar(b.id, 'name', e.target.value)} />
              <input className={`${inputCls} w-40`} placeholder="Slesh negozio id" value={b.slesh_negozio_id} onChange={(e) => updateBar(b.id, 'slesh_negozio_id', e.target.value)} />
              <select className={`${inputCls} w-28 bg-white`} value={b.bar_type} onChange={(e) => updateBar(b.id, 'bar_type', e.target.value as 'drinks' | 'food')}><option value="drinks">drinks</option><option value="food">food</option></select>
              <input className={`${inputCls} w-32`} placeholder="Categoria" value={b.slesh_category} onChange={(e) => updateBar(b.id, 'slesh_category', e.target.value)} />
              <button onClick={() => removeBar(b.id)} className="text-[#E53E3E] text-sm px-2">✕</button>
            </div>))}
            {bars.length === 0 && <p className="text-sm text-[#718096]">No bars yet — add the bars from your Device Count sheet.</p>}
          </div>
        </div>
      )}

      {tab === 3 && (
        <div className="space-y-2 max-w-md">
          {payloadBars.length === 0 ? <p className="text-sm text-[#718096]">Add bars first (Bars tab).</p> : payloadBars.map((b) => (<div key={b.id} className="flex items-center gap-3"><span className="flex-1 text-sm text-[#1A202C]">{b.name}</span><input type="number" min={0} className={`${inputCls} w-28`} value={b.device_count} onChange={(e) => updateBar(b.id, 'device_count', Number(e.target.value) || 0)} /></div>))}
        </div>
      )}

      {tab === 4 && (
        <div>
          <button onClick={addListini} className="mb-3 text-sm font-semibold text-white px-3 py-1.5 rounded-lg bg-[#3182CE]">+ Add product</button>
          <div className="space-y-2">
            {listini.map((r) => (<div key={r.id} className="flex flex-wrap gap-2 items-center">
              <select className={`${inputCls} w-40 bg-white`} value={r.bar_id ?? ''} onChange={(e) => updateListini(r.id, 'bar_id', e.target.value ? Number(e.target.value) : null)}><option value="">Negozio…</option>{payloadBars.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
              <input className={`${inputCls} flex-1 min-w-[140px]`} placeholder="Nome" value={r.name} onChange={(e) => updateListini(r.id, 'name', e.target.value)} />
              <select className={`${inputCls} w-24 bg-white`} value={r.product_type} onChange={(e) => updateListini(r.id, 'product_type', e.target.value as 'drink' | 'food')}><option value="drink">drink</option><option value="food">food</option></select>
              <input className={`${inputCls} w-20`} placeholder="€" value={r.price} onChange={(e) => updateListini(r.id, 'price', e.target.value)} />
              <input className={`${inputCls} w-16`} placeholder="IVA%" value={r.iva} onChange={(e) => updateListini(r.id, 'iva', e.target.value)} />
              <input className={`${inputCls} w-24`} placeholder="Cauzione €" value={r.cauzione} onChange={(e) => updateListini(r.id, 'cauzione', e.target.value)} />
              <button onClick={() => removeListini(r.id)} className="text-[#E53E3E] text-sm px-2">✕</button>
            </div>))}
            {listini.length === 0 && <p className="text-sm text-[#718096]">No products yet — one row per Listini line (Negozio + Nome + Prezzo).</p>}
          </div>
        </div>
      )}

      {tab === 5 && (
        <div>
          {payloadBars.length === 0 || uniqueProducts.length === 0 ? <p className="text-sm text-[#718096]">Add bars and Listini products first — the grid builds from them.</p> : (
            <div className="overflow-x-auto border border-[#E2E8F0] rounded-lg">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50"><tr><th className="sticky left-0 bg-gray-50 px-3 py-2 text-left font-medium text-[#4A5568] border-b min-w-[180px]">Product</th>{payloadBars.map((b) => <th key={b.id} className="px-2 py-2 text-center font-medium text-[#4A5568] border-b whitespace-nowrap">{b.name}</th>)}</tr></thead>
                <tbody>{uniqueProducts.map((p) => (<tr key={p.key} className="odd:bg-white even:bg-gray-50/40"><td className="sticky left-0 bg-inherit px-3 py-1.5 border-b border-gray-100 text-[#1A202C]">{p.name}</td>{payloadBars.map((b) => { const k = `${b.id}|${p.key}`; return (<td key={k} className="px-2 py-1 border-b border-gray-100 text-center"><input type="number" min={0} value={alloc[k] ?? 0} onChange={(e) => setAlloc((prev) => ({ ...prev, [k]: Math.max(0, Math.floor(Number(e.target.value) || 0)) }))} className="w-16 text-center border border-gray-200 rounded px-1 py-0.5" /></td>) })}</tr>))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 6 && (<div className="text-sm text-[#718096] max-w-lg"><p className="mb-2">Lineup (3 stages × 5 slots) is captured closer to the event.</p><p>Stages/lineup tables are deferred (Phase B4); this tab mirrors the Slesh sheet order.</p></div>)}
    </div>
  )
}
