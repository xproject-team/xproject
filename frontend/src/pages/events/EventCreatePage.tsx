import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

// ─── Types ────────────────────────────────────────────────────────────────────

interface BarRow     { id: number; name: string }
interface MenuRow    { id: number; product_name: string; category: string; tier: string; price: string }
interface RecipeRow  { id: number; drink_name: string; bottle_type: string; ml_per_serve: number; bottle_size_ml: number }
interface StockCell  { bar_id: number; product_id: number; quantity: number }

// ─── Seed data ────────────────────────────────────────────────────────────────

const SEED_BARS: BarRow[] = [
  { id: 1, name: 'Main Bar' },
  { id: 2, name: 'VIP Lounge' },
  { id: 3, name: 'Pool Bar' },
  { id: 4, name: 'DJ Booth' },
]

const SEED_MENU: MenuRow[] = [
  { id: 1, product_name: 'Heineken',       category: 'Beer',    tier: 'B', price: '6.00' },
  { id: 2, product_name: 'Absolut Vodka',  category: 'Spirits', tier: 'S', price: '9.50' },
  { id: 3, product_name: 'Moët & Chandon', category: 'Wine',    tier: 'P', price: '45.00' },
  { id: 4, product_name: 'Tonic Water',    category: 'Mixers',  tier: 'U', price: '3.00' },
  { id: 5, product_name: 'Bacardi Rum',    category: 'Spirits', tier: 'S', price: '9.00' },
]

const SEED_RECIPES: RecipeRow[] = [
  { id: 1, drink_name: 'G&T',        bottle_type: 'Gin',   ml_per_serve: 50,  bottle_size_ml: 700 },
  { id: 2, drink_name: 'Vodka Soda', bottle_type: 'Vodka', ml_per_serve: 50,  bottle_size_ml: 700 },
  { id: 3, drink_name: 'Mojito',     bottle_type: 'Rum',   ml_per_serve: 60,  bottle_size_ml: 700 },
]

function buildSeedStock(bars: BarRow[], products: MenuRow[]): StockCell[] {
  const defaults = [24, 20, 20, 48, 20]
  return bars.flatMap((bar) =>
    products.map((p, pi) => ({
      bar_id: bar.id,
      product_id: p.id,
      quantity: defaults[pi] ?? 12,
    })),
  )
}

// ─── Small UI atoms ───────────────────────────────────────────────────────────

function SectionHeader({
  title,
  open,
  onToggle,
}: {
  title: string
  open: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center justify-between px-5 py-4 bg-[#F7FAFC] hover:bg-[#EDF2F7] transition-colors"
    >
      <span className="text-sm font-bold text-[#1A202C]">{title}</span>
      <svg
        className={`w-4 h-4 text-[#4A5568] transition-transform ${open ? 'rotate-180' : ''}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
      </svg>
    </button>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs font-semibold text-[#4A5568] mb-1.5 uppercase tracking-wide">
      {children}
    </label>
  )
}

const inputCls =
  'w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#1A202C] bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition'

const selectCls =
  'border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-xs text-[#1A202C] bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition'

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ visible }: { visible: boolean }) {
  return (
    <div
      className={[
        'fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-[#1A202C] text-white text-sm font-medium px-5 py-3 rounded-xl shadow-lg transition-all duration-300',
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none',
      ].join(' ')}
    >
      <svg className="w-4 h-4 text-[#38A169] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
      </svg>
      Event saved as draft
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EventCreatePage() {
  const navigate = useNavigate()

  // Accordion state — section 1 open by default
  const [open, setOpen] = useState<Record<number, boolean>>({ 1: true, 2: false, 3: false, 4: false, 5: false })
  function toggle(n: number) { setOpen((prev) => ({ ...prev, [n]: !prev[n] })) }

  // Section 1 — Event Details
  const [eventName,   setEventName]   = useState('')
  const [eventDate,   setEventDate]   = useState('')
  const [guests,      setGuests]      = useState('')
  const [venue,       setVenue]       = useState('')

  // Section 2 — Bar Configuration
  const [bars,    setBars]    = useState<BarRow[]>(SEED_BARS)
  const [nextBarId, setNextBarId] = useState(5)

  function addBar() {
    setBars((prev) => [...prev, { id: nextBarId, name: '' }])
    setNextBarId((n) => n + 1)
  }
  function updateBarName(id: number, name: string) {
    setBars((prev) => prev.map((b) => (b.id === id ? { ...b, name } : b)))
  }
  function removeBar(id: number) {
    setBars((prev) => prev.filter((b) => b.id !== id))
  }

  // Section 3 — Menu
  const [menu,      setMenu]      = useState<MenuRow[]>(SEED_MENU)
  const [nextMenuId, setNextMenuId] = useState(6)

  function addProduct() {
    setMenu((prev) => [
      ...prev,
      { id: nextMenuId, product_name: '', category: 'Spirits', tier: 'B', price: '' },
    ])
    setNextMenuId((n) => n + 1)
  }
  function updateMenu<K extends keyof MenuRow>(id: number, key: K, val: MenuRow[K]) {
    setMenu((prev) => prev.map((r) => (r.id === id ? { ...r, [key]: val } : r)))
  }
  function removeMenu(id: number) {
    setMenu((prev) => prev.filter((r) => r.id !== id))
  }

  // Section 4 — Recipes
  const [recipes,     setRecipes]     = useState<RecipeRow[]>(SEED_RECIPES)
  const [nextRecipeId, setNextRecipeId] = useState(4)

  function addRecipe() {
    setRecipes((prev) => [
      ...prev,
      { id: nextRecipeId, drink_name: '', bottle_type: '', ml_per_serve: 50, bottle_size_ml: 700 },
    ])
    setNextRecipeId((n) => n + 1)
  }
  function updateRecipe<K extends keyof RecipeRow>(id: number, key: K, val: RecipeRow[K]) {
    setRecipes((prev) => prev.map((r) => (r.id === id ? { ...r, [key]: val } : r)))
  }
  function removeRecipe(id: number) {
    setRecipes((prev) => prev.filter((r) => r.id !== id))
  }

  // Section 5 — Stock Allocation
  const [stock, setStock] = useState<StockCell[]>(() => buildSeedStock(SEED_BARS, SEED_MENU))

  function getStock(barId: number, productId: number) {
    return stock.find((c) => c.bar_id === barId && c.product_id === productId)?.quantity ?? 0
  }
  function setCell(barId: number, productId: number, quantity: number) {
    setStock((prev) => {
      const idx = prev.findIndex((c) => c.bar_id === barId && c.product_id === productId)
      if (idx === -1) return [...prev, { bar_id: barId, product_id: productId, quantity }]
      return prev.map((c, i) => (i === idx ? { ...c, quantity } : c))
    })
  }

  // Toast
  const [toastVisible, setToastVisible] = useState(false)
  const showToast = useCallback(() => {
    setToastVisible(true)
    setTimeout(() => setToastVisible(false), 3000)
  }, [])

  return (
    <div className="p-6 max-w-4xl mx-auto pb-20">

      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">Create New Event</h1>
          <p className="text-sm text-[#4A5568] mt-1">Configure event settings, bars, menu, and stock</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate('/events')}
            className="text-sm font-semibold text-[#4A5568] border border-[#E2E8F0] px-4 py-2 rounded-lg hover:bg-[#F7FAFC] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={showToast}
            className="text-sm font-semibold text-white px-4 py-2 rounded-lg transition-colors"
            style={{ backgroundColor: '#1ABC9C' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#17a589')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = '#1ABC9C')}
          >
            Save Draft
          </button>
        </div>
      </div>

      {/* Accordion wrapper */}
      <div className="space-y-3">

        {/* ── Section 1 — Event Details ───────────────────────────────── */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <SectionHeader title="1 — Event Details" open={open[1]} onToggle={() => toggle(1)} />
          {open[1] && (
            <div className="px-5 py-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label>Event Name</Label>
                <input
                  type="text"
                  value={eventName}
                  onChange={(e) => setEventName(e.target.value)}
                  placeholder="e.g. Sundance 2026"
                  className={inputCls}
                />
              </div>
              <div>
                <Label>Date</Label>
                <input
                  type="date"
                  value={eventDate}
                  onChange={(e) => setEventDate(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <Label>Expected Guests</Label>
                <input
                  type="number"
                  value={guests}
                  onChange={(e) => setGuests(e.target.value)}
                  placeholder="350"
                  min={1}
                  className={inputCls}
                />
              </div>
              <div>
                <Label>Venue</Label>
                <input
                  type="text"
                  value={venue}
                  onChange={(e) => setVenue(e.target.value)}
                  placeholder="e.g. Villa Roma"
                  className={inputCls}
                />
              </div>
            </div>
          )}
        </div>

        {/* ── Section 2 — Bar Configuration ──────────────────────────── */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <SectionHeader title="2 — Bar Configuration" open={open[2]} onToggle={() => toggle(2)} />
          {open[2] && (
            <div className="px-5 py-5">
              <div className="space-y-2 mb-4">
                {bars.map((bar, idx) => (
                  <div key={bar.id} className="flex items-center gap-3">
                    <span className="text-xs font-bold text-[#4A5568] w-5 shrink-0">{idx + 1}.</span>
                    <input
                      type="text"
                      value={bar.name}
                      onChange={(e) => updateBarName(bar.id, e.target.value)}
                      placeholder="Bar name"
                      className={`${inputCls} flex-1`}
                    />
                    <button
                      type="button"
                      onClick={() => removeBar(bar.id)}
                      className="w-8 h-8 shrink-0 flex items-center justify-center rounded-lg border border-[#E2E8F0] text-[#4A5568] hover:text-[#E53E3E] hover:border-red-200 hover:bg-red-50 transition-colors"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={addBar}
                className="flex items-center gap-1.5 text-xs font-semibold text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#EBF5FB] transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Bar
              </button>
            </div>
          )}
        </div>

        {/* ── Section 3 — Menu Configuration ─────────────────────────── */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <SectionHeader title="3 — Menu Configuration" open={open[3]} onToggle={() => toggle(3)} />
          {open[3] && (
            <div className="px-5 py-5">
              <div className="overflow-x-auto">
                <table className="w-full text-xs mb-4">
                  <thead>
                    <tr className="border-b border-[#E2E8F0]">
                      {['Product Name', 'Category', 'Tier', 'Price (€)', ''].map((h) => (
                        <th key={h} className="text-left text-[10px] font-bold text-[#4A5568] uppercase tracking-wide py-2 pr-3">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {menu.map((row) => (
                      <tr key={row.id} className="border-b border-[#F7FAFC]">
                        <td className="py-2 pr-3">
                          <input
                            type="text"
                            value={row.product_name}
                            onChange={(e) => updateMenu(row.id, 'product_name', e.target.value)}
                            placeholder="Product name"
                            className={`${inputCls} text-xs py-1.5`}
                          />
                        </td>
                        <td className="py-2 pr-3">
                          <select
                            value={row.category}
                            onChange={(e) => updateMenu(row.id, 'category', e.target.value)}
                            className={selectCls}
                          >
                            {['Spirits', 'Beer', 'Wine', 'Mixers', 'Other'].map((c) => (
                              <option key={c}>{c}</option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 pr-3">
                          <select
                            value={row.tier}
                            onChange={(e) => updateMenu(row.id, 'tier', e.target.value)}
                            className={selectCls}
                          >
                            {['B', 'S', 'P', 'U'].map((t) => (
                              <option key={t}>{t}</option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 pr-3">
                          <input
                            type="number"
                            value={row.price}
                            onChange={(e) => updateMenu(row.id, 'price', e.target.value)}
                            placeholder="0.00"
                            step="0.50"
                            min="0"
                            className={`${inputCls} text-xs py-1.5 w-24`}
                          />
                        </td>
                        <td className="py-2">
                          <button
                            type="button"
                            onClick={() => removeMenu(row.id)}
                            className="w-7 h-7 flex items-center justify-center rounded-lg border border-[#E2E8F0] text-[#4A5568] hover:text-[#E53E3E] hover:border-red-200 hover:bg-red-50 transition-colors"
                          >
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                onClick={addProduct}
                className="flex items-center gap-1.5 text-xs font-semibold text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#EBF5FB] transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Product
              </button>
            </div>
          )}
        </div>

        {/* ── Section 4 — Recipes ─────────────────────────────────────── */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <SectionHeader title="4 — Recipes" open={open[4]} onToggle={() => toggle(4)} />
          {open[4] && (
            <div className="px-5 py-5">
              <div className="overflow-x-auto">
                <table className="w-full text-xs mb-4">
                  <thead>
                    <tr className="border-b border-[#E2E8F0]">
                      {['Drink Name', 'Bottle Type', 'ml / Serve', 'Bottle Size ml', 'Drinks / Bottle', ''].map((h) => (
                        <th key={h} className="text-left text-[10px] font-bold text-[#4A5568] uppercase tracking-wide py-2 pr-3 whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {recipes.map((row) => {
                      const drinksPerBottle =
                        row.ml_per_serve > 0
                          ? Math.floor(row.bottle_size_ml / row.ml_per_serve)
                          : 0
                      return (
                        <tr key={row.id} className="border-b border-[#F7FAFC]">
                          <td className="py-2 pr-3">
                            <input
                              type="text"
                              value={row.drink_name}
                              onChange={(e) => updateRecipe(row.id, 'drink_name', e.target.value)}
                              placeholder="e.g. G&T"
                              className={`${inputCls} text-xs py-1.5`}
                            />
                          </td>
                          <td className="py-2 pr-3">
                            <input
                              type="text"
                              value={row.bottle_type}
                              onChange={(e) => updateRecipe(row.id, 'bottle_type', e.target.value)}
                              placeholder="e.g. Gin"
                              className={`${inputCls} text-xs py-1.5`}
                            />
                          </td>
                          <td className="py-2 pr-3">
                            <input
                              type="number"
                              value={row.ml_per_serve}
                              onChange={(e) => updateRecipe(row.id, 'ml_per_serve', Number(e.target.value))}
                              min={1}
                              className={`${inputCls} text-xs py-1.5 w-20`}
                            />
                          </td>
                          <td className="py-2 pr-3">
                            <input
                              type="number"
                              value={row.bottle_size_ml}
                              onChange={(e) => updateRecipe(row.id, 'bottle_size_ml', Number(e.target.value))}
                              min={1}
                              className={`${inputCls} text-xs py-1.5 w-24`}
                            />
                          </td>
                          <td className="py-2 pr-3">
                            <span className="inline-block bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg px-3 py-1.5 font-bold text-[#1A202C] tabular-nums w-16 text-center">
                              {drinksPerBottle}
                            </span>
                          </td>
                          <td className="py-2">
                            <button
                              type="button"
                              onClick={() => removeRecipe(row.id)}
                              className="w-7 h-7 flex items-center justify-center rounded-lg border border-[#E2E8F0] text-[#4A5568] hover:text-[#E53E3E] hover:border-red-200 hover:bg-red-50 transition-colors"
                            >
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <button
                type="button"
                onClick={addRecipe}
                className="flex items-center gap-1.5 text-xs font-semibold text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#EBF5FB] transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Recipe
              </button>
            </div>
          )}
        </div>

        {/* ── Section 5 — Initial Stock Allocation ────────────────────── */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
          <SectionHeader title="5 — Initial Stock Allocation" open={open[5]} onToggle={() => toggle(5)} />
          {open[5] && (
            <div className="px-5 py-5">
              {bars.length === 0 || menu.length === 0 ? (
                <p className="text-sm text-[#4A5568] italic">
                  Add bars and products in sections 2 and 3 first.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="text-xs">
                    <thead>
                      <tr className="border-b border-[#E2E8F0]">
                        <th className="text-left text-[10px] font-bold text-[#4A5568] uppercase tracking-wide py-2 pr-4 whitespace-nowrap min-w-[140px]">
                          Product
                        </th>
                        {bars.map((bar) => (
                          <th
                            key={bar.id}
                            className="text-center text-[10px] font-bold text-[#4A5568] uppercase tracking-wide py-2 px-2 whitespace-nowrap"
                          >
                            {bar.name || `Bar ${bar.id}`}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {menu.map((product) => (
                        <tr key={product.id} className="border-b border-[#F7FAFC]">
                          <td className="py-2 pr-4 font-medium text-[#1A202C] whitespace-nowrap">
                            {product.product_name || `Product ${product.id}`}
                          </td>
                          {bars.map((bar) => (
                            <td key={bar.id} className="py-2 px-2 text-center">
                              <input
                                type="number"
                                value={getStock(bar.id, product.id)}
                                onChange={(e) => setCell(bar.id, product.id, Number(e.target.value))}
                                min={0}
                                className="w-16 border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-xs text-center text-[#1A202C] bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/30 focus:border-[#1E5A8D] transition tabular-nums"
                              />
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

      </div>{/* /accordion */}

      <Toast visible={toastVisible} />
    </div>
  )
}
