import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

import { useCreateProduct, type ProductCreatePayload, type ProductType } from '@/features/products/hooks'

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
  const [category,    setCategory]    = useState('')
  const [unit,        setUnit]        = useState('glass')
  const [priceEur,    setPriceEur]    = useState('')
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
      category:            category.trim() || null,
      unit:                unit.trim(),
      default_price_cents: priceCents,
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
    <div className="flex flex-col h-full bg-white">
      <div className="flex items-center justify-between border-b border-[#E2E8F0] px-6 py-4">
        <div>
          <button onClick={() => navigate('/products')} className="text-xs text-[#1E5A8D] hover:underline mb-1">← Back to Products</button>
          <h1 className="text-xl font-bold text-[#1A202C]">Create Product</h1>
        </div>
        <div className="flex gap-2">
          <button onClick={() => navigate('/products')} className="text-sm font-medium text-[#4A5568] px-4 py-2 rounded-lg hover:bg-[#F7FAFC]">Cancel</button>
          <button onClick={handleSubmit} disabled={createMutation.isPending} className="text-sm font-medium text-white bg-[#1E5A8D] px-4 py-2 rounded-lg hover:bg-[#174870] transition-colors disabled:bg-[#A0AEC0]">
            {createMutation.isPending ? 'Creating…' : 'Create product'}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl space-y-5">
          <Field label="Name" error={errors.name} required>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" placeholder="e.g. Cocktail" autoFocus />
          </Field>

          <Field label="Type">
            <select value={productType} onChange={(e) => setProductType(e.target.value as ProductType)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm bg-white">
              {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Field>

          <Field label="Category">
            <input type="text" value={category} onChange={(e) => setCategory(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" placeholder="e.g. cocktail, beer" />
          </Field>

          <Field label="Unit" error={errors.unit} required hint="e.g. glass, bottle, kg, piece">
            <input type="text" value={unit} onChange={(e) => setUnit(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" />
          </Field>

          <Field label="Default price (EUR)" hint="Optional. Used as fallback when Slesh doesn't include line price.">
            <input type="number" min="0" step="0.01" value={priceEur} onChange={(e) => setPriceEur(e.target.value)} className="w-full border border-[#E2E8F0] rounded px-3 py-2 text-sm" placeholder="e.g. 10" />
          </Field>
        </div>
      </div>
    </div>
  )
}

function Field({ label, hint, error, required, children }: { label: string; hint?: string; error?: string; required?: boolean; children: React.ReactNode }) {
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
