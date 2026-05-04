import { useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'

import {
  useProduct,
  useUpdateProduct,
  useArchiveProduct,
  type ProductUpdatePayload,
  type ProductType,
} from '@/features/products/hooks'
import type { ProductRow } from '@/lib/mockData'

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: product, isLoading, isError, error } = useProduct(id)

  if (isLoading) {
    return <div className="flex items-center justify-center h-full text-sm text-[#718096]">Loading product…</div>
  }
  if (isError) {
    return (
      <div className="m-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
        Failed to load product: {(error as Error)?.message ?? 'unknown error'}
      </div>
    )
  }
  if (!product) {
    return <div className="m-6 text-sm text-[#718096]">Product not found.</div>
  }

  return <ProductDetailContent product={product} />
}

function ProductDetailContent({ product }: { product: ProductRow }) {
  const navigate = useNavigate()
  const updateMutation  = useUpdateProduct()
  const archiveMutation = useArchiveProduct()

  const [name,             setName]             = useState(product.name)
  const [category,         setCategory]         = useState(product.category ?? '')
  const [unit,             setUnit]             = useState(product.unit)
  const [priceCents,       setPriceCents]       = useState<string>(
    product.default_price_cents != null ? String(product.default_price_cents / 100) : '',
  )
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)

  const dirty =
    name        !== product.name        ||
    (category || null) !== (product.category ?? null) ||
    unit        !== product.unit        ||
    parsePriceCents(priceCents) !== product.default_price_cents

  const handleSave = async () => {
    if (!dirty) return
    const payload: ProductUpdatePayload = {}
    if (name        !== product.name)                payload.name      = name.trim()
    if ((category || null) !== (product.category ?? null)) payload.category = category.trim() || null
    if (unit        !== product.unit)                payload.unit      = unit.trim()
    const newPrice = parsePriceCents(priceCents)
    if (newPrice !== product.default_price_cents)    payload.default_price_cents = newPrice
    try {
      await updateMutation.mutateAsync({ id: product.id, payload })
    } catch (err) {
      console.error('Failed to update product:', err)
      alert(`Update failed: ${(err as Error)?.message ?? 'unknown error'}`)
    }
  }

  const handleArchive = async () => {
    try {
      await archiveMutation.mutateAsync(product.id)
      navigate('/products')
    } catch (err) {
      console.error('Failed to archive product:', err)
      alert(`Archive failed: ${(err as Error)?.message ?? 'unknown error'}`)
      setShowArchiveConfirm(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <button onClick={() => navigate('/products')} className="text-xs text-[#1E5A8D] hover:underline mb-1">← Back to Products</button>
          <h1 className="text-xl font-bold text-[#1A202C]">{product.name}</h1>
          <p className="text-xs text-[#4A5568] mt-0.5">
            Type: {product.product_type} · Tier: {product.tier_rank ?? '—'}
            {product.is_archived && <span className="ml-2 text-[#718096]">(archived)</span>}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={!dirty || updateMutation.isPending}
            className={`text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
              dirty && !updateMutation.isPending
                ? 'text-white bg-[#1E5A8D] hover:bg-[#174870]'
                : 'text-[#A0AEC0] bg-[#F7FAFC] cursor-not-allowed'
            }`}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </button>
          {!product.is_archived && (
            <button
              onClick={() => setShowArchiveConfirm(true)}
              disabled={archiveMutation.isPending}
              className="text-sm font-medium text-[#E53E3E] border border-[#E53E3E] px-4 py-2 rounded-lg hover:bg-red-50 transition-colors"
            >
              Archive
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl space-y-5">
          <Field label="Name">
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" />
          </Field>
          <Field label="Category">
            <input type="text" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" placeholder="e.g. cocktail, beer, soft" />
          </Field>
          <Field label="Unit" hint="e.g. glass, bottle, kg, piece">
            <input type="text" value={unit} onChange={(e) => setUnit(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" />
          </Field>
          <Field label="Default price (EUR)" hint="Used as fallback when Slesh order doesn't include line price">
            <input type="number" min="0" step="0.01" value={priceCents} onChange={(e) => setPriceCents(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" placeholder="e.g. 10" />
          </Field>

          <div className="pt-4 border-t border-[#E2E8F0]">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-2">Metadata</h2>
            <div className="grid grid-cols-2 gap-3 text-xs text-[#4A5568]">
              <div><span className="font-medium">ID:</span> <span className="font-mono">{product.id}</span></div>
              <div><span className="font-medium">Type:</span> {product.product_type} (immutable)</div>
            </div>
          </div>
        </div>
      </div>

      {showArchiveConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-[#1A202C] mb-2">Archive product?</h3>
            <p className="text-sm text-[#4A5568] mb-4">
              <span className="font-semibold">{product.name}</span> will be hidden from default lists but kept in the database for historical accuracy.
              Existing transactions and recipes referencing it remain unchanged. You can unarchive later by editing the product.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowArchiveConfirm(false)} className="text-sm font-medium text-[#4A5568] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]">Cancel</button>
              <button onClick={handleArchive} disabled={archiveMutation.isPending} className="text-sm font-medium text-white bg-[#E53E3E] px-4 py-2 rounded-lg hover:bg-[#C53030] transition-colors">
                {archiveMutation.isPending ? 'Archiving…' : 'Archive'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function parsePriceCents(input: string): number | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  const eur = parseFloat(trimmed)
  if (!Number.isFinite(eur) || eur < 0) return null
  return Math.round(eur * 100)
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-[#4A5568] mb-1">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-[#A0AEC0] mt-1">{hint}</p>}
    </div>
  )
}
