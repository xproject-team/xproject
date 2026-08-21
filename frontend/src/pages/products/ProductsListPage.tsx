import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { CATEGORY_LABELS, useProducts } from '@/features/products/hooks'
import type { ProductCategory } from '@/features/products/hooks'
import type { ProductRow } from '@/lib/mockData'
import { Badge, Button, EmptyState, PageHeader } from '@/design-system/components'
import '@/design-system/components/components.css'
import { colorForCategory } from '@/design-system/categoricalPalette'

type FilterKey = 'all' | 'drink' | 'food' | 'ingredient' | 'supply'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all',        label: 'All'        },
  { key: 'drink',      label: 'Drinks'     },
  { key: 'food',       label: 'Food'       },
  { key: 'ingredient', label: 'Ingredients'},
  { key: 'supply',     label: 'Supplies'   },
]

const TYPE_CFG: Record<string, { label: string; variant: 'info' | 'violet' | 'warning' | 'neutral' }> = {
  drink:      { label: 'Drink',      variant: 'info'    },
  food:       { label: 'Food',       variant: 'violet'  },
  ingredient: { label: 'Ingredient', variant: 'warning' },
  supply:     { label: 'Supply',     variant: 'neutral' },
}

function TypeBadge({ type }: { type: string }) {
  const cfg = TYPE_CFG[type] ?? TYPE_CFG.supply
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>
}

// Categories are drink-only and there are 8 of them — same shape as chart
// series, so reuse the deterministic hash palette rather than trying to
// squeeze 8 values into the 6 fixed Badge variants.
function CategoryBadge({ category }: { category: ProductCategory }) {
  const color = colorForCategory(category)
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 12%, transparent)`,
        color,
        border: `0.5px solid ${color}`,
      }}
    >
      {CATEGORY_LABELS[category]}
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
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <PageHeader
          title="Products"
          subtitle="Shared across every event — a product entered once is reused everywhere, never re-created per event."
          actions={
            <Button variant="primary" onClick={() => navigate('/products/new')}>
              <span className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Create Product
              </span>
            </Button>
          }
        />
      </div>

      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <label className="flex items-center gap-2 text-xs" style={{ color: 'var(--v-text-muted)' }}>
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
            className="h-3.5 w-3.5"
          />
          Show archived
        </label>

        <div className="flex gap-1.5 ml-2">
          {FILTERS.map((f) => {
            const isActive = activeTab === f.key
            return (
              <button
                key={f.key}
                onClick={() => setActiveTab(f.key)}
                className="text-xs font-medium px-3 py-1.5 rounded-full transition-colors"
                style={{
                  background: isActive ? 'rgba(0, 229, 212, 0.12)' : 'var(--v-surface)',
                  color: isActive ? 'var(--v-cyan)' : 'var(--v-text-muted)',
                  border: `0.5px solid ${isActive ? 'var(--v-cyan)' : 'var(--v-border)'}`,
                }}
              >
                {f.label} <span className="opacity-75">({counts[f.key]})</span>
              </button>
            )
          })}
        </div>
      </div>

      <div
        className="overflow-hidden"
        style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius-lg)' }}
      >
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--v-surface-raised)', borderBottom: '0.5px solid var(--v-border)' }}>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Name</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Type</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Category</th>
              <th className="text-left px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Unit</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}>Default price</th>
              <th className="text-right px-5 py-3 text-[10px] font-bold uppercase tracking-[0.06em]" style={{ color: 'var(--v-text-muted)' }}></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-5 py-12 text-center text-sm" style={{ color: 'var(--v-text-muted)' }}>
                  <div className="inline-flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full animate-spin" style={{ border: '2px solid var(--v-border)', borderTopColor: 'var(--v-cyan)' }} />
                    Loading products…
                  </div>
                </td>
              </tr>
            )}

            {isError && !isLoading && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center">
                  <div className="inline-flex items-start gap-2 text-sm" style={{ color: 'var(--v-pink)' }}>
                    <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                    <span>
                      Failed to load products.
                      {error instanceof Error && <span className="block text-xs mt-1" style={{ color: 'var(--v-text-dim)' }}>{error.message}</span>}
                    </span>
                  </div>
                </td>
              </tr>
            )}

            {!isLoading && !isError && visibleProducts.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-12">
                  <EmptyState
                    headline={products.length === 0 ? 'No products yet' : `No ${activeTab} products`}
                    body={products.length === 0 ? 'Click "Create Product" to add the first one.' : 'Try a different filter.'}
                  />
                </td>
              </tr>
            )}

            {!isLoading && !isError && visibleProducts.map((p) => {
              const textColor = p.is_archived ? 'var(--v-text-muted)' : 'var(--v-text)'
              return (
                <tr
                  key={p.id}
                  className="transition-colors last:border-0"
                  style={{ borderBottom: '0.5px solid var(--v-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td className="px-5 py-4 font-medium" style={{ color: textColor }}>
                    {p.name}
                    {p.is_archived && (
                      <span className="ml-2 text-[10px] font-medium" style={{ color: 'var(--v-text-dim)' }}>(archived)</span>
                    )}
                  </td>
                  <td className="px-5 py-4"><TypeBadge type={p.product_type} /></td>
                  <td className="px-5 py-4">
                    {p.category ? <CategoryBadge category={p.category as ProductCategory} /> : <span style={{ color: 'var(--v-text-dim)' }}>—</span>}
                  </td>
                  <td className="px-5 py-4 text-xs" style={{ color: 'var(--v-text-muted)' }}>{p.unit}</td>
                  <td className="px-5 py-4 text-right font-medium" style={{ color: 'var(--v-text)' }}>{fmtEur(p.default_price_cents)}</td>
                  <td className="px-5 py-4 text-right">
                    <Button variant="secondary" onClick={() => navigate(`/products/${p.id}`)}>
                      View
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
