import { useSearchParams } from 'react-router-dom'

import ProductsListPage from '@/pages/products/ProductsListPage'
import { EventRecipesTab } from '@/pages/catalog/EventRecipesTab'
import { PageHeader } from '@/design-system/components'
import '@/design-system/components/components.css'

type Tab = 'products' | 'recipes'

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: 'products', label: 'Products', hint: 'Drinks, food, ingredients, and supplies' },
  { key: 'recipes',  label: 'Recipes',  hint: 'Which bottles each drink consumes, per event — feeds depletion alerts' },
]

export default function CatalogPage() {
  // Persist the active tab in the URL so a refresh — or a bookmark —
  // returns the user to the same tab they were on. Defaults to
  // 'products' if the query param is missing or invalid.
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  const active: Tab = rawTab === 'recipes' ? 'recipes' : 'products'
  const setActive = (t: Tab) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (t === 'products') next.delete('tab')
      else next.set('tab', t)
      return next
    }, { replace: true })
  }

  return (
    <div>
      {/* ProductsListPage/EventRecipesTab each self-centre at max-w-6xl —
          same route is also reachable standalone at /products, so that
          page owns its own layout rather than relying on this shell. Only
          the tab chrome itself is centred here, to avoid doubling the
          padding when embedded. */}
      <div className="p-6 pb-0 max-w-6xl mx-auto">
        <div className="mb-6">
          <PageHeader
            title="Catalog"
            subtitle="Products and recipes shared across your events"
          />
        </div>

        <div className="flex items-center gap-2 mb-2">
          {TABS.map((t) => {
            const isActive = active === t.key
            return (
              <button
                key={t.key}
                onClick={() => setActive(t.key)}
                title={t.hint}
                className="text-sm font-medium px-4 py-2 rounded-full transition-colors"
                style={{
                  background: isActive ? 'rgba(0, 229, 212, 0.12)' : 'transparent',
                  color: isActive ? 'var(--v-cyan)' : 'var(--v-text-muted)',
                }}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Tab content — only the active one mounts */}
      {active === 'products' && <ProductsListPage />}
      {active === 'recipes'  && <EventRecipesTab  />}
    </div>
  )
}
