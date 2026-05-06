import { useNavigate, useParams } from 'react-router-dom'
import { useState, useMemo } from 'react'

import {
  useRecipe,
  useUpdateRecipe,
  useDeleteRecipe,
  useAddRecipeItem,
  useUpdateRecipeItem,
  useDeleteRecipeItem,
  type RecipeWithItems,
  type ProductUnit,
  type RecipeUpdatePayload,
} from '@/features/recipes/hooks'
import { useProducts } from '@/features/products/hooks'

// ─── Constants ────────────────────────────────────────────────────────

const UNITS: ProductUnit[] = [
  'glass', 'bottle', 'can', 'piece', 'kg', 'g',
  'l', 'ml', 'oz', 'shot', 'dash', 'serving',
]

// ─── Wrapper ──────────────────────────────────────────────────────────

export default function RecipeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: recipe, isLoading, isError, error } = useRecipe(id)

  if (isLoading) {
    return <div className="flex items-center justify-center h-full text-sm text-[#718096]">Loading recipe…</div>
  }
  if (isError) {
    return (
      <div className="m-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
        Failed to load recipe: {(error as Error)?.message ?? 'unknown error'}
      </div>
    )
  }
  if (!recipe) {
    return <div className="m-6 text-sm text-[#718096]">Recipe not found.</div>
  }

  return <RecipeDetailContent recipe={recipe} />
}

// ─── Inner content ────────────────────────────────────────────────────

function RecipeDetailContent({ recipe }: { recipe: RecipeWithItems }) {
  const navigate = useNavigate()

  const updateRecipe = useUpdateRecipe()
  const deleteRecipe = useDeleteRecipe()
  const addItem      = useAddRecipeItem()
  const updateItem   = useUpdateRecipeItem()
  const deleteItem   = useDeleteRecipeItem()

  const { data: products = [] } = useProducts(true)
  const drinkProduct = useMemo(
    () => products.find((p) => p.id === recipe.drink_product_id),
    [products, recipe.drink_product_id],
  )
  const drinkName = drinkProduct?.name ?? '(unknown drink)'
  const drinkPriceCents = drinkProduct?.default_price_cents ?? null
  const productNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of products) m.set(p.id, p.name)
    return m
  }, [products])

  // Recipe-header edit state
  const [yieldQty,   setYieldQty]   = useState<string>(String(recipe.yield_qty))
  const [yieldUnit,  setYieldUnit]  = useState<ProductUnit>(recipe.yield_unit)
  const [notes,      setNotes]      = useState<string>(recipe.notes ?? '')
  const [showDelete, setShowDelete] = useState(false)

  // New-item form state
  const [newIngId, setNewIngId] = useState<string>('')
  const [newQty,   setNewQty]   = useState<string>('')
  const [newUnit,  setNewUnit]  = useState<ProductUnit>('ml')
  const [newNote,  setNewNote]  = useState<string>('')

  // Eligible ingredient products (everything EXCEPT the drink itself, not archived).
  const eligibleIngredients = useMemo(
    () => products.filter((p) => p.id !== recipe.drink_product_id && !p.is_archived),
    [products, recipe.drink_product_id],
  )

  const headerDirty =
    parseFloat(yieldQty) !== recipe.yield_qty ||
    yieldUnit            !== recipe.yield_unit ||
    (notes || null)       !== (recipe.notes ?? null)

  const handleSaveHeader = async () => {
    if (!headerDirty) return
    const payload: RecipeUpdatePayload = {}
    const qtyNum = parseFloat(yieldQty)
    if (Number.isFinite(qtyNum) && qtyNum > 0 && qtyNum !== recipe.yield_qty) payload.yield_qty = qtyNum
    if (yieldUnit !== recipe.yield_unit) payload.yield_unit = yieldUnit
    if ((notes || null) !== (recipe.notes ?? null)) payload.notes = notes.trim() || null
    try {
      await updateRecipe.mutateAsync({ id: recipe.id, payload })
    } catch (err) {
      alert(`Update failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  const handleDelete = async () => {
    try {
      await deleteRecipe.mutateAsync(recipe.id)
      navigate('/catalog')
    } catch (err) {
      alert(`Delete failed: ${(err as Error)?.message ?? 'unknown error'}`)
      setShowDelete(false)
    }
  }

  const handleAddItem = async () => {
    if (!newIngId) { alert('Pick an ingredient'); return }
    const qty = parseFloat(newQty)
    if (!Number.isFinite(qty) || qty <= 0) { alert('Quantity must be a positive number'); return }
    try {
      await addItem.mutateAsync({
        recipeId: recipe.id,
        payload: {
          ingredient_product_id: newIngId,
          qty,
          unit: newUnit,
          note: newNote.trim() || null,
        },
      })
      // Reset the new-item form
      setNewIngId('')
      setNewQty('')
      setNewNote('')
    } catch (err) {
      alert(`Add ingredient failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  const handleDeleteItem = async (itemId: string) => {
    if (!confirm('Remove this ingredient?')) return
    try {
      await deleteItem.mutateAsync({ itemId, recipeId: recipe.id })
    } catch (err) {
      alert(`Remove failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <button onClick={() => navigate('/catalog')} className="text-xs text-[#1E5A8D] hover:underline mb-1">
            ← Back to Catalog
          </button>
          <h1 className="text-xl font-bold text-[#1A202C]">{drinkName}</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            Recipe · {recipe.items.length} ingredient{recipe.items.length === 1 ? '' : 's'} · yields{' '}
            {recipe.yield_qty} {recipe.yield_unit}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSaveHeader}
            disabled={!headerDirty || updateRecipe.isPending}
            className={`text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
              headerDirty && !updateRecipe.isPending
                ? 'text-white bg-[#1E5A8D] hover:bg-[#174870]'
                : 'text-[#A0AEC0] bg-[#F7FAFC] cursor-not-allowed'
            }`}
          >
            {updateRecipe.isPending ? 'Saving…' : 'Save changes'}
          </button>
          <button
            onClick={() => setShowDelete(true)}
            disabled={deleteRecipe.isPending}
            className="text-sm font-medium text-[#E53E3E] border border-[#E53E3E] px-4 py-2 rounded-lg hover:bg-red-50 transition-colors"
          >
            Delete recipe
          </button>
        </div>
      </div>

      {/* Body — three stacked sections */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">
        {/* ── Section 0: price summary (read-only here; edited in Products) ── */}
        <section className="max-w-2xl">
          <div className="bg-sky-50 border border-sky-200 rounded-lg px-4 py-3 text-sm flex items-center justify-between">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wider text-[#4A5568]">
                Sale price
              </div>
              <div className="text-lg font-bold text-[#1A202C] mt-0.5">
                {drinkPriceCents !== null
                  ? new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(drinkPriceCents / 100)
                  : 'not set'}
              </div>
            </div>
            {drinkProduct && (
              <button
                onClick={() => navigate(`/products/${drinkProduct.id}`)}
                className="text-xs font-medium text-[#1E5A8D] border border-[#1E5A8D] px-3 py-1.5 rounded-lg hover:bg-[#F0F7FF] transition-colors"
                title="Price lives on the product (single source of truth). Editing here would create drift with Slesh."
              >
                Edit price
              </button>
            )}
          </div>
        </section>

        {/* ── Section 1: header form ── */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-3">
            Recipe header
          </h2>
          <div className="grid grid-cols-2 gap-4 max-w-xl">
            <Field label="Yield quantity" hint="How many output units one execution of this recipe produces">
              <input
                type="number" min="0" step="0.01"
                value={yieldQty} onChange={(e) => setYieldQty(e.target.value)}
                className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
              />
            </Field>
            <Field label="Yield unit">
              <select
                value={yieldUnit} onChange={(e) => setYieldUnit(e.target.value as ProductUnit)}
                className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
              >
                {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </Field>
            <div className="col-span-2">
              <Field label="Notes" hint="Free-form notes for the bartender (technique, garnish, etc.)">
                <textarea
                  value={notes} onChange={(e) => setNotes(e.target.value)}
                  rows={2}
                  className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
                  placeholder="e.g. shake vigorously, garnish with mint sprig"
                />
              </Field>
            </div>
          </div>
        </section>

        {/* ── Section 2: ingredient list ── */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-3">
            Ingredients ({recipe.items.length})
          </h2>

          {recipe.items.length === 0 && (
            <p className="text-sm text-[#718096] italic mb-4">
              No ingredients yet. Add the first one below.
            </p>
          )}

          {recipe.items.length > 0 && (
            <table className="w-full text-sm mb-6">
              <thead>
                <tr className="text-left text-[11px] font-semibold uppercase text-[#4A5568] border-b border-[#E2E8F0]">
                  <th className="py-2 pr-4">Ingredient</th>
                  <th className="py-2 pr-4 w-28">Quantity</th>
                  <th className="py-2 pr-4 w-24">Unit</th>
                  <th className="py-2 pr-4">Note</th>
                  <th className="py-2 pr-4 w-20"></th>
                </tr>
              </thead>
              <tbody>
                {recipe.items.map((item) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    productName={productNameById.get(item.ingredient_product_id) ?? '(unknown)'}
                    onUpdate={(payload) =>
                      updateItem.mutateAsync({ itemId: item.id, recipeId: recipe.id, payload })
                    }
                    onDelete={() => handleDeleteItem(item.id)}
                  />
                ))}
              </tbody>
            </table>
          )}

          {/* New-item form */}
          <div className="border-t border-[#E2E8F0] pt-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-3">
              Add ingredient
            </h3>
            <div className="grid grid-cols-12 gap-2 max-w-3xl items-end">
              <div className="col-span-5">
                <select
                  value={newIngId} onChange={(e) => setNewIngId(e.target.value)}
                  className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
                >
                  <option value="">— pick an ingredient —</option>
                  {eligibleIngredients.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.product_type})</option>
                  ))}
                </select>
              </div>
              <div className="col-span-2">
                <input
                  type="number" min="0" step="0.01"
                  value={newQty} onChange={(e) => setNewQty(e.target.value)}
                  placeholder="qty"
                  className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm"
                />
              </div>
              <div className="col-span-2">
                <select
                  value={newUnit} onChange={(e) => setNewUnit(e.target.value as ProductUnit)}
                  className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white"
                >
                  {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
                </select>
              </div>
              <div className="col-span-3">
                <button
                  onClick={handleAddItem}
                  disabled={addItem.isPending || !newIngId || !newQty}
                  className="w-full text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors disabled:bg-[#A0AEC0]"
                >
                  {addItem.isPending ? 'Adding…' : 'Add'}
                </button>
              </div>
            </div>
            <input
              type="text"
              value={newNote} onChange={(e) => setNewNote(e.target.value)}
              placeholder="Optional note (e.g. fresh-squeezed, premium)"
              className="mt-2 w-full max-w-3xl border border-[#E2E8F0] rounded px-3 py-2 text-sm"
            />
          </div>
        </section>
      </div>

      {/* Delete confirmation modal */}
      {showDelete && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-[#1A202C] mb-2">Delete recipe?</h3>
            <p className="text-sm text-[#4A5568] mb-4">
              Deleting this recipe is permanent and removes its {recipe.items.length} ingredient
              line{recipe.items.length === 1 ? '' : 's'}. The drink product itself is not affected.
              Stock-transaction cascade for past sales is preserved.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowDelete(false)} className="text-sm font-medium text-[#4A5568] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]">
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteRecipe.isPending}
                className="text-sm font-medium text-white bg-[#E53E3E] px-4 py-2 rounded-lg hover:bg-[#C53030] transition-colors"
              >
                {deleteRecipe.isPending ? 'Deleting…' : 'Delete recipe'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── ItemRow — inline-editable single ingredient ──────────────────────

interface ItemRowProps {
  item:        RecipeWithItems['items'][number]
  productName: string
  onUpdate:    (payload: { qty?: number; unit?: ProductUnit; note?: string | null }) => Promise<unknown>
  onDelete:    () => void
}

function ItemRow({ item, productName, onUpdate, onDelete }: ItemRowProps) {
  const [qty,  setQty]  = useState<string>(String(item.qty))
  const [unit, setUnit] = useState<ProductUnit>(item.unit)
  const [note, setNote] = useState<string>(item.note ?? '')

  const dirty =
    parseFloat(qty)   !== item.qty   ||
    unit              !== item.unit  ||
    (note || null)    !== (item.note ?? null)

  const handleSave = async () => {
    if (!dirty) return
    const payload: { qty?: number; unit?: ProductUnit; note?: string | null } = {}
    const qtyNum = parseFloat(qty)
    if (Number.isFinite(qtyNum) && qtyNum > 0 && qtyNum !== item.qty) payload.qty  = qtyNum
    if (unit !== item.unit) payload.unit = unit
    if ((note || null) !== (item.note ?? null)) payload.note = note.trim() || null
    try {
      await onUpdate(payload)
    } catch (err) {
      alert(`Update failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  return (
    <tr className="border-b border-[#F7FAFC]">
      <td className="py-2 pr-4 font-medium text-[#1A202C]">{productName}</td>
      <td className="py-2 pr-4">
        <input
          type="number" min="0" step="0.01"
          value={qty} onChange={(e) => setQty(e.target.value)}
          onBlur={handleSave}
          className="w-20 border border-[#E2E8F0] rounded px-2 py-1 text-sm"
        />
      </td>
      <td className="py-2 pr-4">
        <select
          value={unit} onChange={(e) => { setUnit(e.target.value as ProductUnit); }}
          onBlur={handleSave}
          className="border border-[#E2E8F0] rounded px-2 py-1 text-sm bg-white"
        >
          {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
      </td>
      <td className="py-2 pr-4">
        <input
          type="text"
          value={note} onChange={(e) => setNote(e.target.value)}
          onBlur={handleSave}
          placeholder="—"
          className="w-full border border-[#E2E8F0] rounded px-2 py-1 text-sm"
        />
      </td>
      <td className="py-2 pr-4">
        <button onClick={onDelete} className="text-xs text-[#E53E3E] hover:underline">Remove</button>
      </td>
    </tr>
  )
}

// ─── Field wrapper ────────────────────────────────────────────────────

function Field({
  label, hint, children,
}: {
  label: string; hint?: string; children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-1">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}
