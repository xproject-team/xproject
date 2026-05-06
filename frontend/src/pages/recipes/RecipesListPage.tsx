import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { useRecipes } from '@/features/recipes/hooks'
import { useProducts } from '@/features/products/hooks'
import type { RecipeWithItems } from '@/features/recipes/hooks'
import type { ProductRow } from '@/lib/mockData'

// ─── Helpers ──────────────────────────────────────────────────────────

/**
 * Format a quantity + unit. "50 ml" rather than the raw decimal.
 * Per-ingredient unit is preserved (the recipe item carries its own unit;
 * we trust the backend\'s storage choice).
 */
function fmtQty(qty: number, unit: string): string {
  // Trim trailing zeros: 50.000 -> 50; 0.500 -> 0.5
  const trimmed = parseFloat(qty.toFixed(3)).toString()
  return `${trimmed} ${unit}`
}

/**
 * One-line summary of the ingredient list, used in the table:
 *   "50 ml gin · 30 ml lime · 20 ml syrup · soda"
 * Truncated if very long.
 */
function summarizeItems(
  items: RecipeWithItems['items'],
  productNameById: Map<string, string>,
): string {
  if (!items.length) return '(no ingredients yet)'
  const parts = items.map((it) => {
    const name = productNameById.get(it.ingredient_product_id) ?? '(unknown)'
    return `${fmtQty(it.qty, it.unit)} ${name}`
  })
  const joined = parts.join(' · ')
  return joined.length > 120 ? joined.slice(0, 117) + '…' : joined
}


// ─── Component ────────────────────────────────────────────────────────

export default function RecipesListPage() {
  const navigate = useNavigate()

  const { data: recipes  = [], isLoading: rLoading, isError: rErr, error: rError } = useRecipes()
  const { data: products = [], isLoading: pLoading } = useProducts(true)

  const productById = useMemo(() => {
    const m = new Map<string, ProductRow>()
    for (const p of products) m.set(p.id, p)
    return m
  }, [products])

  const productNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of products) m.set(p.id, p.name)
    return m
  }, [products])

  const isLoading = rLoading || pLoading

  return (
    <div className="flex flex-col flex-1">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-[#E2E8F0]">
        <div>
          <h2 className="text-base font-bold text-[#1A202C]">Drink Recipes</h2>
          <p className="text-xs text-[#4A5568] mt-0.5">
            {recipes.length} recipe{recipes.length === 1 ? '' : 's'} · used to compute expected
            consumption per drink sold and detect over-pour anomalies
          </p>
        </div>
        <button
          onClick={() => navigate('/catalog/recipes/new')}
          className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors"
        >
          + Create Recipe
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading && (
          <div className="text-center text-sm text-[#718096] py-12">Loading recipes…</div>
        )}
        {rErr && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
            Failed to load recipes: {(rError as Error)?.message ?? 'unknown error'}
          </div>
        )}
        {!isLoading && !rErr && recipes.length === 0 && (
          <div className="text-center text-sm text-[#718096] py-12">
            No recipes yet. Click "+ Create Recipe" to define your first drink.
          </div>
        )}

        {!isLoading && !rErr && recipes.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-semibold uppercase text-[#4A5568] border-b border-[#E2E8F0]">
                <th className="py-2 pr-4">Drink</th>
                <th className="py-2 pr-4">Yield</th>
                <th className="py-2 pr-4">Ingredients</th>
                <th className="py-2 pr-4 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {recipes.map((r) => {
                const drinkName = productById.get(r.drink_product_id)?.name ?? '(unknown drink)'
                return (
                  <tr key={r.id} className="border-b border-[#F7FAFC] hover:bg-[#F7FAFC]">
                    <td className="py-3 pr-4 font-medium text-[#1A202C]">{drinkName}</td>
                    <td className="py-3 pr-4 text-[#4A5568]">{fmtQty(r.yield_qty, r.yield_unit)}</td>
                    <td className="py-3 pr-4 text-[#4A5568] text-xs">
                      {summarizeItems(r.items, productNameById)}
                    </td>
                    <td className="py-3 pr-4">
                      <button
                        onClick={() => navigate(`/catalog/recipes/${r.id}`)}
                        className="text-xs font-medium text-[#1E5A8D] hover:underline"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
