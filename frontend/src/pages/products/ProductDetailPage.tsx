import { useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'

import {
  useProduct,
  useUpdateProduct,
  useArchiveProduct,
  type ProductUpdatePayload,
  type ProductCategory,
  type ProductUnit,
  CATEGORY_OPTIONS,
  UNIT_OPTIONS,
} from '@/features/products/hooks'
import type { ProductRow } from '@/lib/mockData'
import { Button, GlassPanel } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label, HelperText } from '@/design-system/wizardForm'

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data: product, isLoading, isError, error } = useProduct(id)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--v-text-muted)' }}>
        Loading product…
      </div>
    )
  }
  if (isError) {
    return (
      <div className="m-6 max-w-2xl mx-auto rounded-lg px-4 py-3 text-sm" style={{ background: 'rgba(255, 61, 113, 0.08)', border: '0.5px solid var(--v-pink)', color: 'var(--v-pink)' }}>
        Failed to load product: {(error as Error)?.message ?? 'unknown error'}
      </div>
    )
  }
  if (!product) {
    return <div className="m-6 text-sm" style={{ color: 'var(--v-text-muted)' }}>Product not found.</div>
  }

  return <ProductDetailContent product={product} />
}

function ProductDetailContent({ product }: { product: ProductRow }) {
  const navigate = useNavigate()
  const updateMutation  = useUpdateProduct()
  const archiveMutation = useArchiveProduct()

  const [name,             setName]             = useState(product.name)
  const [category,         setCategory]         = useState<ProductCategory | ''>((product.category as ProductCategory | null) ?? '')
  const [unit,             setUnit]             = useState<ProductUnit>(product.unit as ProductUnit)
  const [priceCents,       setPriceCents]       = useState<string>(
    product.default_price_cents != null ? String(product.default_price_cents / 100) : '',
  )
  const [barcode,           setBarcode]           = useState(product.barcode ?? '')
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
  const dirty =
    name !== product.name
    || (category || null) !== (product.category ?? null)
    || unit !== product.unit
    || parsePriceCents(priceCents) !== product.default_price_cents
    || barcode !== (product.barcode ?? '')

  const handleSave = async () => {
    if (!dirty) return
    const payload: ProductUpdatePayload = {}
    if (name        !== product.name)                payload.name      = name.trim()
    if ((category || null) !== (product.category ?? null)) payload.category = category || null
    if (unit        !== product.unit)                payload.unit      = unit
    const newPrice = parsePriceCents(priceCents)
    if (newPrice !== product.default_price_cents)    payload.default_price_cents = newPrice
    if (barcode    !== (product.barcode ?? ''))      payload.barcode   = barcode.trim() || null
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
    <div className="p-6 max-w-2xl mx-auto">
      <button
        onClick={() => navigate('/products')}
        className="text-xs mb-3 hover:underline"
        style={{ color: 'var(--v-cyan)' }}
      >
        ← Back to Products
      </button>

      <div className="flex items-start justify-between mb-6 gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-medium" style={{ color: 'var(--v-text)' }}>{product.name}</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--v-text-muted)' }}>
            Type: {product.product_type} · Tier: {product.tier_rank ?? '—'}
            {product.is_archived && <span className="ml-2" style={{ color: 'var(--v-text-dim)' }}>(archived)</span>}
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button variant="primary" onClick={handleSave} disabled={!dirty || updateMutation.isPending}>
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
          {!product.is_archived && (
            <button
              onClick={() => setShowArchiveConfirm(true)}
              disabled={archiveMutation.isPending}
              className="text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              style={{ color: 'var(--v-pink)', border: '0.5px solid var(--v-pink)' }}
            >
              Archive
            </button>
          )}
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <Label>Name</Label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={inputCls} />
        </div>
        {product.product_type === 'drink' && (
          <div>
            <Label>Category</Label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as ProductCategory | '')}
              className={inputCls}
            >
              <option value="">— none —</option>
              {CATEGORY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <HelperText>Drives the default tier rank.</HelperText>
          </div>
        )}
        <div>
          <Label>Unit</Label>
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value as ProductUnit)}
            className={inputCls}
          >
            {UNIT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <Label>Default price (EUR)</Label>
          <input type="number" min="0" step="0.01" value={priceCents} onChange={(e) => setPriceCents(e.target.value)} className={inputCls} placeholder="e.g. 10" />
          <HelperText>Used as fallback when Slesh order doesn't include line price.</HelperText>
        </div>
        <div>
          <Label>Barcode</Label>
          <input
            type="text"
            inputMode="numeric"
            value={barcode}
            onChange={(e) => setBarcode(e.target.value.replace(/\s/g, ''))}
            className={`${inputCls} font-mono`}
            placeholder="e.g. 7501055309603"
            maxLength={64}
          />
          <HelperText>Optional. EAN-13 / UPC-A / Code-128. Scanner uses this to identify the product.</HelperText>
        </div>

        <div className="pt-4" style={{ borderTop: '0.5px solid var(--v-border)' }}>
          <p className="text-[10px] font-bold uppercase tracking-[0.06em] mb-2" style={{ color: 'var(--v-text-muted)' }}>Metadata</p>
          <div className="grid grid-cols-2 gap-3 text-xs" style={{ color: 'var(--v-text-muted)' }}>
            <div><span className="font-medium" style={{ color: 'var(--v-text)' }}>ID:</span> <span className="font-mono">{product.id}</span></div>
            <div><span className="font-medium" style={{ color: 'var(--v-text)' }}>Type:</span> {product.product_type} (immutable)</div>
          </div>
        </div>
      </div>

      {showArchiveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <GlassPanel className="rounded-2xl max-w-md w-[90%] mx-4 p-6">
            <h3 className="text-lg font-medium mb-2" style={{ color: 'var(--v-text)' }}>Archive product?</h3>
            <p className="text-sm mb-4 leading-relaxed" style={{ color: 'var(--v-text-muted)' }}>
              <span className="font-semibold" style={{ color: 'var(--v-text)' }}>{product.name}</span> will be hidden
              from default lists but kept in the database for historical accuracy. Existing transactions and recipes
              referencing it remain unchanged. You can unarchive later by editing the product.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowArchiveConfirm(false)}>
                Cancel
              </Button>
              <button
                onClick={handleArchive}
                disabled={archiveMutation.isPending}
                className="text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                style={{ background: 'var(--v-pink)', color: '#1a0508' }}
              >
                {archiveMutation.isPending ? 'Archiving…' : 'Archive'}
              </button>
            </div>
          </GlassPanel>
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
