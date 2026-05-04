import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useProducts } from '@/features/products/hooks'
import type { ProductRow } from '@/lib/mockData'

type FilterKey = 'all' | 'drink' | 'food' | 'ingredient' | 'supply'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all',        label: 'All'        },
  { key: 'drink',      label: 'Drinks'     },
  { key: 'food',       label: 'Food'       },
  { key: 'ingredient', label: 'Ingredients'},
  { key: 'supply',     label: 'Supplies'   },
]

const TYPE_CFG: Record<string, { cls: string }> = {
  drink:      { cls: 'bg-sky-50    text-sky-800    border border-sky-200'    },
  food:       { cls: 'bg-amber-50  text-amber-800  border border-amber-200'  },
  ingredient: { cls: 'bg-purple-50 text-purple-800 border border-purple-200' },
  supply:     { cls: 'bg-zinc-50   text-zinc-800   border border-zinc-200'   },
}

function TypeBadge({ type }: { type: string }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG.supply
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${cfg.cls}`}>
      {type}
    </span>
  )
}

function fmtEur(cents: number | null): string {
  if (cents === null || cents === undefined) return '—'
  return new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(cents / 100)
}

export default function ProductsListPage() {
  const navigate = useNavigate()
  const [includeArchived, setIncludeArchived] = useState(false)
  const [activeTab,        setActiveTab]      = useState<FilterKey>('all')

  const { data: products = [], isLoading, isError, error } = useProducts(includeArchived)

  const visibleProducts = useMemo<ProductRow[]>(
    () => activeTab === 'all' ? products : products.filter((p) => p.product_type === activeTab),
    [activeTab, products],
  )

  const counts = useMemo(() => ({
    all:        products.length,
    drink:      products.filter((p) => p.product_type === 'drink').length,
    food:       products.filter((p) => p.product_type === 'food').length,
    ingredient: products.filter((p) => p.product_type === 'ingredient').length,
    supply:     products.filter((p) => p.product_type === 'supply').length,
  }), [products])

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <h1 className="text-xl font-bold text-[#1A202C]">Products</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            {counts.all} total · {counts.drink} drinks · {counts.food} food · {counts.ingredient} ingredients · {counts.supply} supplies
          </p>
        </div>
        <button
          onClick={() => navigate('/products/new')}
          className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors"
        >
          + Create Product
        </button>
      </div>

      <div className="flex items-center gap-3 border-b border-[#E2E8F0] px-6 py-3">
        <label className="flex items-center gap-2 text-xs text-[#4A5568]">
          <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} className="h-3.5 w-3.5" />
          Show archived
        </label>

        <div className="flex gap-1 ml-4">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setActiveTab(f.key)}
              className={[
                'text-xs font-medium px-3 py-1 rounded-full transition-colors',
                activeTab === f.key ? 'bg-[#1E5A8D] text-white' : 'text-[#4A5568] hover:bg-[#F7FAFC]',
              ].join(' ')}
            >
              {f.label} <span className="opacity-75">({counts[f.key]})</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading && <div className="text-center text-sm text-[#718096] py-12">Loading products…</div>}
        {isError && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
            Failed to load products: {(error as Error)?.message ?? 'unknown error'}
          </div>
        )}
        {!isLoading && !isError && visibleProducts.length === 0 && (
          <div className="text-center text-sm text-[#718096] py-12">
            {products.length === 0 ? 'No products yet. Click "+ Create Product" to add one.' : `No ${activeTab} products.`}
          </div>
        )}

        {!isLoading && !isError && visibleProducts.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-semibold uppercase text-[#4A5568] border-b border-[#E2E8F0]">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Type</th>
                <th className="py-2 pr-4">Category</th>
                <th className="py-2 pr-4">Unit</th>
                <th className="py-2 pr-4">Default price</th>
                <th className="py-2 pr-4 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {visibleProducts.map((p) => (
                <tr key={p.id} className={`border-b border-[#F7FAFC] hover:bg-[#F7FAFC] ${p.is_archived ? 'opacity-50' : ''}`}>
                  <td className="py-3 pr-4 font-medium text-[#1A202C]">
                    {p.name}
                    {p.is_archived && <span className="ml-2 text-[10px] font-medium text-[#718096]">(archived)</span>}
                  </td>
                  <td className="py-3 pr-4"><TypeBadge type={p.product_type} /></td>
                  <td className="py-3 pr-4 text-[#4A5568] text-xs">{p.category ?? '—'}</td>
                  <td className="py-3 pr-4 text-[#4A5568] text-xs">{p.unit}</td>
                  <td className="py-3 pr-4 text-[#1A202C]">{fmtEur(p.default_price_cents)}</td>
                  <td className="py-3 pr-4">
                    <button
                      onClick={() => navigate(`/products/${p.id}`)}
                      className="text-xs font-medium text-[#1E5A8D] hover:underline"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
