import { useSearchParams } from 'react-router-dom'

import ProductsListPage from '@/pages/products/ProductsListPage'
import { EventRecipesTab } from '@/pages/catalog/EventRecipesTab'

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
    <div className="flex flex-col h-full bg-white">
      {/* Top tab bar */}
      <div className="flex items-center gap-1 border-b border-[#E2E8F0] px-6 pt-3">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={[
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              active === t.key
                ? 'border-[#1E5A8D] text-[#1E5A8D]'
                : 'border-transparent text-[#4A5568] hover:text-[#1A202C]',
            ].join(' ')}
            title={t.hint}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content — only the active one mounts */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {active === 'products' && <ProductsListPage />}
        {active === 'recipes'  && <EventRecipesTab  />}
      </div>
    </div>
  )
}
