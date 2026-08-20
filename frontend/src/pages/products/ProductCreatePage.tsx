import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

import {
  useCreateProduct,
  type ProductCreatePayload,
  type ProductType,
  type ProductCategory,
  type ProductUnit,
  CATEGORY_OPTIONS,
  UNIT_OPTIONS,
} from '@/features/products/hooks'
import { Button } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label, HelperText } from '@/design-system/wizardForm'

const TYPE_OPTIONS: { value: ProductType; label: string }[] = [
  { value: 'drink',      label: 'Drink'      },
  { value: 'food',       label: 'Food'       },
  { value: 'ingredient', label: 'Ingredient' },
  { value: 'supply',     label: 'Supply'     },
]

interface FormErrors {
  name?: string
  unit?: string
}

export default function ProductCreatePage() {
  const navigate = useNavigate()
  const createMutation = useCreateProduct()

  const [name,        setName]        = useState('')
  const [productType, setProductType] = useState<ProductType>('drink')
  const [category,    setCategory]    = useState<ProductCategory | ''>('')
  const [unit,        setUnit]        = useState<ProductUnit>('glass')
  const [priceEur,    setPriceEur]    = useState('')
  const [barcode,     setBarcode]     = useState('')
  const [errors,      setErrors]      = useState<FormErrors>({})

  const validate = (): FormErrors => {
    const e: FormErrors = {}
    if (!name.trim()) e.name = 'Name is required'
    if (!unit.trim()) e.unit = 'Unit is required'
    return e
  }

  const handleSubmit = async () => {
    const errs = validate()
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    const eur = priceEur.trim() ? parseFloat(priceEur) : NaN
    const priceCents = Number.isFinite(eur) && eur >= 0 ? Math.round(eur * 100) : null

    const payload: ProductCreatePayload = {
      name:                name.trim(),
      product_type:        productType,
      category:            productType === 'drink' && category ? category : null,
      unit:                unit,
      default_price_cents: priceCents,
      barcode:             barcode.trim() || null,
    }
    try {
      const created = await createMutation.mutateAsync(payload)
      navigate(`/products/${created.id}`)
    } catch (err) {
      console.error('Failed to create product:', err)
      alert(`Create failed: ${(err as Error)?.message ?? 'unknown error'}`)
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

      <h1 className="text-2xl font-medium mb-1" style={{ color: 'var(--v-text)' }}>Create Product</h1>
      <p className="text-sm mb-6" style={{ color: 'var(--v-text-muted)' }}>
        Products are shared across every event — this one will be available to reuse everywhere, not just here.
      </p>

      <div className="space-y-5">
        <div>
          <Label>Name *</Label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
            placeholder="e.g. Cocktail"
            autoFocus
          />
          {errors.name && <p className="text-[12px] mt-1" style={{ color: 'var(--v-pink)' }}>{errors.name}</p>}
        </div>

        <div>
          <Label>Type</Label>
          <select
            value={productType}
            onChange={(e) => setProductType(e.target.value as ProductType)}
            className={inputCls}
          >
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {productType === 'drink' && (
          <div>
            <Label>Category</Label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as ProductCategory | '')}
              className={inputCls}
            >
              <option value="">— select —</option>
              {CATEGORY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <HelperText>Drives the default tier rank.</HelperText>
          </div>
        )}

        <div>
          <Label>Unit *</Label>
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value as ProductUnit)}
            className={inputCls}
          >
            {UNIT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {errors.unit && <p className="text-[12px] mt-1" style={{ color: 'var(--v-pink)' }}>{errors.unit}</p>}
        </div>

        <div>
          <Label>Default price (EUR)</Label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={priceEur}
            onChange={(e) => setPriceEur(e.target.value)}
            className={inputCls}
            placeholder="e.g. 10"
          />
          <HelperText>Optional. Used as fallback when Slesh doesn't include line price.</HelperText>
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

        <div className="flex gap-2 pt-2">
          <Button variant="primary" onClick={handleSubmit} disabled={createMutation.isPending}>
            {createMutation.isPending ? 'Creating…' : 'Create product'}
          </Button>
          <Button variant="ghost" onClick={() => navigate('/products')}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  )
}
