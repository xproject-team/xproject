import { useNavigate } from 'react-router-dom'
import { useState, useMemo } from 'react'

import {
  useCreateRecipeWithItems,
  useRecipes,
  type ProductUnit,
  type RecipeItemCreateInPayload,
  type RecipeWithItemsCreatePayload,
} from '@/features/recipes/hooks'
import {
  useRecipeTemplates,
  type RecipeTemplate,
  type RecipeTemplateItem,
} from '@/features/recipes/useRecipeTemplates'
import { useProducts } from '@/features/products/hooks'
import type { ProductRow } from '@/lib/mockData'

const UNITS: ProductUnit[] = [
  'glass', 'shot', 'ml', 'oz', 'bottle', 'can', 'piece', 'dash',
]

interface BoundIngredient {
  /** Stable row key. */
  rowKey:                string
  /** From the template, fixed at "selection time". null when user picked Custom. */
  template_role:         string | null
  template_label:        string | null
  /** Owner picks from their Products. Empty until bound. */
  ingredient_product_id: string
  /** From template (default), editable. */
  qty:                   string
  unit:                  ProductUnit
  /** Optional skip flag — owner can skip this ingredient role from his menu. */
  skip:                  boolean
}

function fmtEur(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return ''
  return new Intl.NumberFormat('it-IT', {
    style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
  }).format(cents / 100)
}

function templateItemToBound(item: RecipeTemplateItem): BoundIngredient {
  return {
    rowKey:                Math.random().toString(36).slice(2),
    template_role:         item.ingredient_role,
    template_label:        item.ingredient_label,
    ingredient_product_id: '',
    qty:                   String(item.qty),
    unit:                  (UNITS.includes(item.unit as ProductUnit) ? item.unit : 'ml') as ProductUnit,
    skip:                  false,
  }
}

function emptyCustomRow(): BoundIngredient {
  return {
    rowKey:                Math.random().toString(36).slice(2),
    template_role:         null,
    template_label:        null,
    ingredient_product_id: '',
    qty:                   '',
    unit:                  'ml',
    skip:                  false,
  }
}

export default function RecipeCreatePage() {
  const navigate = useNavigate()

  const { data: products  = [] } = useProducts(false)
  const { data: existingRecipes = [] } = useRecipes()
  const { data: templates = [], isLoading: tLoading } = useRecipeTemplates()
  const createMutation = useCreateRecipeWithItems()

  // Step 1 — template selection (null = Custom path)
  const [selectedTemplate, setSelectedTemplate] = useState<RecipeTemplate | null | "CUSTOM">(null)
  const [searchQ,         setSearchQ]           = useState("")
  const [categoryFilter,  setCategoryFilter]    = useState<string>("")

  // Step 2 — ingredient bindings
  const [bindings, setBindings] = useState<BoundIngredient[]>([])

  // Step 3 — drink + display_name + yield + notes
  const [drinkProductId, setDrinkProductId] = useState("")
  const [displayName,    setDisplayName]    = useState("")
  const [yieldQty,       setYieldQty]       = useState("1")
  const [yieldUnit,      setYieldUnit]      = useState<ProductUnit>("glass")
  const [notes,          setNotes]          = useState("")

  // Drinks already with a recipe — exclude from picker
  const drinksWithRecipe = useMemo(() => {
    const s = new Set<string>()
    for (const r of existingRecipes) s.add(r.drink_product_id)
    return s
  }, [existingRecipes])

  const eligibleDrinks = useMemo(
    () => products
      .filter(p => p.product_type === 'drink')
      .filter(p => !drinksWithRecipe.has(p.id))
      .sort((a, b) => a.name.localeCompare(b.name)),
    [products, drinksWithRecipe],
  )

  const eligibleIngredients = useMemo(
    () => products
      .filter(p => p.id !== drinkProductId)
      .filter(p => !p.is_archived)
      .sort((a, b) => a.name.localeCompare(b.name)),
    [products, drinkProductId],
  )

  const filteredTemplates = useMemo(() => {
    let list = templates
    if (categoryFilter) list = list.filter(t => t.category === categoryFilter)
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase()
      list = list.filter(t => t.name.toLowerCase().includes(q))
    }
    return list
  }, [templates, categoryFilter, searchQ])

  const categories = useMemo(() => {
    const s = new Set<string>()
    for (const t of templates) s.add(t.category)
    return Array.from(s).sort()
  }, [templates])

  // ── Step transitions ──────────────────────────────────────────
  const handlePickTemplate = (t: RecipeTemplate) => {
    setSelectedTemplate(t)
    setBindings(t.items.map(templateItemToBound))
    setDisplayName(t.name) // pre-fill so Owner can edit
  }
  const handlePickCustom = () => {
    setSelectedTemplate("CUSTOM")
    setBindings([emptyCustomRow()])
    setDisplayName("")
  }
  const handleBack = () => {
    setSelectedTemplate(null)
    setBindings([])
    setDisplayName("")
  }

  // ── Binding mutations ─────────────────────────────────────────
  const updateBinding = (rowKey: string, patch: Partial<BoundIngredient>) =>
    setBindings(rows => rows.map(r => r.rowKey === rowKey ? { ...r, ...patch } : r))

  const addCustomRow = () =>
    setBindings(rows => [...rows, emptyCustomRow()])

  const removeRow = (rowKey: string) =>
    setBindings(rows => rows.length > 1 ? rows.filter(r => r.rowKey !== rowKey) : rows)

  // ── Validate + Submit ─────────────────────────────────────────
  const validate = (): string | null => {
    if (!drinkProductId) return "Pick a drink to bind this recipe to"
    const yQ = parseFloat(yieldQty)
    if (!Number.isFinite(yQ) || yQ <= 0) return "Yield must be a positive number"

    const usable = bindings.filter(b => !b.skip)
    if (usable.length === 0) return "Bind at least one ingredient"

    const seen = new Set<string>()
    for (const b of usable) {
      if (!b.ingredient_product_id) return `Pick a product for ${b.template_label ?? "ingredient"}`
      if (seen.has(b.ingredient_product_id)) {
        return `Duplicate product — each ingredient can appear only once`
      }
      seen.add(b.ingredient_product_id)
      const q = parseFloat(b.qty)
      if (!Number.isFinite(q) || q <= 0) return `Quantity for ${b.template_label ?? "ingredient"} must be positive`
    }
    return null
  }

  const handleSubmit = async () => {
    const err = validate()
    if (err) { alert(err); return }

    const payload: RecipeWithItemsCreatePayload = {
      drink_product_id: drinkProductId,
      yield_qty:        parseFloat(yieldQty),
      yield_unit:       yieldUnit,
      notes:            notes.trim() || null,
      display_name:     displayName.trim() || null,
      template_id:      selectedTemplate && selectedTemplate !== "CUSTOM" ? selectedTemplate.id : null,
      items: bindings
        .filter(b => !b.skip)
        .map((b): RecipeItemCreateInPayload => ({
          ingredient_product_id: b.ingredient_product_id,
          qty:                   parseFloat(b.qty),
          unit:                  b.unit,
        })),
    }

    try {
      const created = await createMutation.mutateAsync(payload)
      navigate(`/catalog/recipes/${created.id}`)
    } catch (err) {
      console.error("Failed to create recipe:", err)
      alert(`Create failed: ${(err as Error)?.message ?? "unknown error"}`)
    }
  }

  // ── Render ────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <button onClick={() => navigate("/catalog")} className="text-xs text-[#1E5A8D] hover:underline mb-1">
            ← Back to Catalog
          </button>
          <h1 className="text-xl font-bold text-[#1A202C]">Define a Recipe</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            Pick from the IBA standard library, then bind ingredients to YOUR products.
          </p>
        </div>
        {selectedTemplate !== null && (
          <button
            onClick={handleSubmit}
            disabled={createMutation.isPending}
            className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] disabled:bg-[#A0AEC0]"
          >
            {createMutation.isPending ? "Creating…" : "Save Recipe"}
          </button>
        )}
      </div>

      {/* STEP 1 — Pick a template */}
      {selectedTemplate === null && (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-3xl">
            <h2 className="text-sm font-semibold text-[#1A202C] mb-3">Step 1 · Pick a base</h2>

            <div className="flex items-center gap-2 mb-3">
              <input
                type="text"
                value={searchQ}
                onChange={e => setSearchQ(e.target.value)}
                placeholder="Search templates… (e.g. mojito)"
                className="flex-1 border border-[#E2E8F0] rounded px-3 py-2 text-sm"
              />
              <select
                value={categoryFilter}
                onChange={e => setCategoryFilter(e.target.value)}
                className="border border-[#E2E8F0] rounded px-2 py-2 text-sm bg-white"
              >
                <option value="">All categories</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {tLoading && <p className="text-sm text-[#718096]">Loading IBA library…</p>}

            {!tLoading && (
              <div className="grid grid-cols-2 gap-2">
                {filteredTemplates.map(t => (
                  <button
                    key={t.id}
                    onClick={() => handlePickTemplate(t)}
                    className="text-left p-3 border border-[#E2E8F0] rounded-lg hover:border-[#1E5A8D] hover:bg-[#F0F7FF] transition-colors"
                  >
                    <div className="flex justify-between items-start">
                      <div className="font-semibold text-sm text-[#1A202C]">{t.name}</div>
                      <span className="text-[10px] uppercase tracking-wider text-[#718096]">{t.category}</span>
                    </div>
                    <p className="text-xs text-[#4A5568] mt-1">
                      {t.items.length} ingredient{t.items.length === 1 ? "" : "s"}
                      {t.total_ml && ` · ${t.total_ml} ml total`}
                      {t.glass_type && ` · ${t.glass_type} glass`}
                    </p>
                    {t.description && (
                      <p className="text-[11px] text-[#A0AEC0] mt-1 italic line-clamp-2">{t.description}</p>
                    )}
                  </button>
                ))}

                <button
                  onClick={handlePickCustom}
                  className="text-left p-3 border-2 border-dashed border-[#A0AEC0] rounded-lg hover:border-[#1E5A8D] hover:bg-[#F0F7FF] transition-colors"
                >
                  <div className="font-semibold text-sm text-[#1A202C]">Custom (no template)</div>
                  <p className="text-xs text-[#4A5568] mt-1">Build the recipe from scratch.</p>
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* STEPS 2 + 3 — Template chosen, bind & save */}
      {selectedTemplate !== null && (
        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-3xl space-y-6">

            {/* Selected template breadcrumb */}
            <div className="bg-sky-50 border border-sky-200 rounded-lg px-4 py-3 text-sm flex items-center justify-between">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-[#4A5568]">Based on</div>
                <div className="font-semibold text-[#1A202C]">
                  {selectedTemplate === "CUSTOM" ? "Custom (no IBA template)" : selectedTemplate.name}
                </div>
                {selectedTemplate !== "CUSTOM" && selectedTemplate.description && (
                  <p className="text-xs text-[#4A5568] mt-0.5 italic">{selectedTemplate.description}</p>
                )}
              </div>
              <button onClick={handleBack} className="text-xs text-[#1E5A8D] hover:underline">
                Change
              </button>
            </div>

            {/* Step 2: bind ingredients */}
            <section>
              <h2 className="text-sm font-semibold text-[#1A202C] mb-2">
                Step 2 · Bind ingredients to your Products
              </h2>
              <p className="text-xs text-[#4A5568] mb-3">
                For each role, pick which of your Products fulfills it. You can skip any role you do not stock.
              </p>

              <div className="border border-[#E2E8F0] rounded-lg divide-y divide-[#F7FAFC]">
                {bindings.map((b, idx) => {
                  const skipped = b.skip
                  return (
                    <div key={b.rowKey} className={`p-3 ${skipped ? "opacity-50" : ""}`}>
                      <div className="grid grid-cols-12 gap-2 items-center">
                        <div className="col-span-3 text-sm font-medium text-[#1A202C]">
                          {b.template_label ?? `Ingredient ${idx + 1}`}
                        </div>
                        <div className="col-span-4">
                          <select
                            value={b.ingredient_product_id}
                            onChange={e => updateBinding(b.rowKey, { ingredient_product_id: e.target.value })}
                            disabled={skipped || !drinkProductId}
                            className="w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-sm bg-white disabled:bg-[#F7FAFC]"
                          >
                            <option value="">— pick product —</option>
                            {eligibleIngredients.map(p => (
                              <option key={p.id} value={p.id}>{p.name}</option>
                            ))}
                          </select>
                        </div>
                        <div className="col-span-2">
                          <input
                            type="number" min="0" step="0.01"
                            value={b.qty}
                            onChange={e => updateBinding(b.rowKey, { qty: e.target.value })}
                            disabled={skipped}
                            className="w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-sm"
                          />
                        </div>
                        <div className="col-span-2">
                          <select
                            value={b.unit}
                            onChange={e => updateBinding(b.rowKey, { unit: e.target.value as ProductUnit })}
                            disabled={skipped}
                            className="w-full border border-[#E2E8F0] rounded px-2 py-1.5 text-sm bg-white"
                          >
                            {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                          </select>
                        </div>
                        <div className="col-span-1 text-right">
                          {b.template_role ? (
                            <button
                              onClick={() => updateBinding(b.rowKey, { skip: !b.skip })}
                              className="text-[11px] font-medium text-[#4A5568] hover:underline"
                              title={skipped ? "Include this role" : "Skip this role"}
                            >
                              {skipped ? "Use" : "Skip"}
                            </button>
                          ) : (
                            <button
                              onClick={() => removeRow(b.rowKey)}
                              disabled={bindings.length === 1}
                              className="text-[11px] font-medium text-[#E53E3E] hover:underline disabled:text-[#A0AEC0]"
                            >
                              Remove
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>

              {selectedTemplate === "CUSTOM" && (
                <button
                  onClick={addCustomRow}
                  className="mt-2 text-xs font-medium text-[#1E5A8D] hover:underline"
                >
                  + Add ingredient
                </button>
              )}
            </section>

            {/* Step 3: details */}
            <section>
              <h2 className="text-sm font-semibold text-[#1A202C] mb-3">Step 3 · Recipe details</h2>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Drink (Slesh product)" required hint="Which Slesh product this recipe is for.">
                  <select
                    value={drinkProductId}
                    onChange={e => setDrinkProductId(e.target.value)}
                    className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
                  >
                    <option value="">— select a drink —</option>
                    {eligibleDrinks.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.default_price_cents != null ? `   ·   ${fmtEur(p.default_price_cents)}` : ""}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Display name" hint="What bartenders see (e.g. 'Sundance Long Island'). Defaults to drink name if blank.">
                  <input
                    type="text"
                    value={displayName}
                    onChange={e => setDisplayName(e.target.value)}
                    placeholder={selectedTemplate !== "CUSTOM" ? selectedTemplate.name : "(uses drink name)"}
                    className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
                  />
                </Field>

                <Field label="Yield qty" required>
                  <input
                    type="number" min="0" step="0.01"
                    value={yieldQty}
                    onChange={e => setYieldQty(e.target.value)}
                    className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
                  />
                </Field>

                <Field label="Yield unit">
                  <select
                    value={yieldUnit}
                    onChange={e => setYieldUnit(e.target.value as ProductUnit)}
                    className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
                  >
                    {UNITS.map(u => <option key={u} value={u}>{u}</option>)}
                  </select>
                </Field>
              </div>

              <div className="mt-4">
                <Field label="Notes" hint="Optional. Bartender-facing notes.">
                  <textarea
                    value={notes} onChange={e => setNotes(e.target.value)} rows={2}
                    className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
                    placeholder="e.g. shake hard, garnish with mint sprig"
                  />
                </Field>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({
  label, hint, error, required, children,
}: {
  label: string; hint?: string; error?: string; required?: boolean; children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-1">
        {label}{required && <span className="text-[#E53E3E] ml-0.5">*</span>}
      </label>
      {children}
      {error && <p className="text-[11px] text-[#E53E3E] mt-1">{error}</p>}
      {hint  && !error && <p className="text-[11px] text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}
