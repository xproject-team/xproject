/**
 * Wizard Step 3 — Products
 *
 * Flat, editable product list. There is deliberately NO per-row "which
 * bar" column: at Sundance every drinks/food bar sells the same menu,
 * so the payload mapper generates menu[] as a cross product (every
 * product × every drinks-or-food bar) rather than Omar picking bars
 * here. Recharge/service bars get no menu rows.
 *
 * Rows come from state.products (pre-populated by Step 2 upload via
 * ProductSpec → ProductDraft mapping, or empty when Omar skips upload).
 *
 * Design choices mirror WizardStep3Bars.tsx: one card per row, footer
 * hint (not hard block) for missing categories.
 */
import { useMemo } from "react"

import type { WizardState, ProductDraft } from "../types"
import { inputCls, Label, stepCardCls, rowCardCls, warningBannerCls, warningBannerStyle } from "@/design-system/wizardForm"
import { EmptyState } from "@/design-system/components"
import "@/design-system/components/components.css"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

function makeClientId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `bd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

const PRODUCT_TYPES: { value: ProductDraft["product_type"]; label: string }[] = [
  { value: "drink",      label: "Drink"      },
  { value: "food",       label: "Food"       },
  { value: "supply",     label: "Supply"     },
  { value: "ingredient", label: "Ingredient" },
]

const CATEGORIES: { value: NonNullable<ProductDraft["category"]>; label: string }[] = [
  { value: "beer_draft",       label: "Beer (draft)"       },
  { value: "beer_bottle",      label: "Beer (bottle)"      },
  { value: "basic_cocktail",   label: "Basic cocktail"     },
  { value: "premium_cocktail", label: "Premium cocktail"   },
  { value: "wine_red",         label: "Wine (red)"         },
  { value: "wine_white",       label: "Wine (white)"       },
  { value: "wine_sparkling",   label: "Wine (sparkling)"   },
  { value: "soft_drink",       label: "Soft drink"         },
]

const FOOD_TYPES: { value: NonNullable<ProductDraft["food_type"]>; label: string }[] = [
  { value: "burgers",    label: "Burgers"    },
  { value: "sandwiches", label: "Sandwiches" },
  { value: "fried",      label: "Fried"      },
  { value: "skewers",    label: "Skewers"    },
  { value: "pizza",      label: "Pizza"      },
  { value: "gelato",     label: "Gelato"     },
  { value: "other",      label: "Other"      },
]

const UNITS: { value: ProductDraft["unit"]; label: string }[] = [
  { value: "bottle",      label: "Bottle"      },
  { value: "glass",       label: "Glass"       },
  { value: "can",         label: "Can"         },
  { value: "draft_glass", label: "Draft glass" },
  { value: "shot",        label: "Shot"        },
  { value: "piece",       label: "Piece"       },
  { value: "gram",        label: "Gram"        },
  { value: "ml",          label: "ml"          },
]

/** Parses a EUR-display string ("8.50") into integer cents (850).
 *  Blank/invalid input falls back to 0. */
function eurosToCents(raw: string): number {
  const n = Number(raw)
  if (!Number.isFinite(n)) return 0
  return Math.round(n * 100)
}

function centsToEurosDisplay(cents: number | null): string {
  if (cents === null) return ""
  return (cents / 100).toFixed(2)
}

function pctToFractionDisplay(frac: number | null): string {
  if (frac === null) return ""
  return String(Math.round(frac * 1000) / 10)
}

export function WizardStep3Products({ state, onChange }: Props) {
  const products = state.products

  // ── Mutations ────────────────────────────────────────────────────
  const updateProduct = (clientId: string, patch: Partial<ProductDraft>) => {
    onChange({
      products: products.map((p) => (p.client_id === clientId ? { ...p, ...patch } : p)),
    })
  }

  const removeProduct = (clientId: string) => {
    onChange({ products: products.filter((p) => p.client_id !== clientId) })
  }

  const addProduct = () => {
    const newProduct: ProductDraft = {
      client_id: makeClientId(),
      name: "",
      product_type: "drink",
      category: null,
      food_type: null,
      unit: "bottle",
      default_price_cents: 0,
      iva_pct: null,
      cauzione_cents: null,
      tier_rank: null,
    }
    onChange({ products: [...products, newProduct] })
  }

  // ── Validation hint ──────────────────────────────────────────────
  const missingCategoryCount = useMemo(
    () => products.filter((p) => p.product_type === "drink" && p.category === null).length,
    [products],
  )

  return (
    <div className={stepCardCls}>
      <div className="mb-4">
        <h2 className="text-base font-medium" style={{ color: "var(--v-text)" }}>Products</h2>
        <p className="text-sm mt-1" style={{ color: "var(--v-text-muted)" }}>
          What each bar sells. Excel-uploaded products appear here for review. Same
          menu at every drinks/food bar — per-bar pricing comes later.
        </p>
      </div>

      {products.length === 0 ? (
        <div className="text-center py-8 rounded-[var(--v-radius)]" style={{ border: "2px dashed var(--v-border)" }}>
          <EmptyState
            headline="No products yet"
            body="Add your first product to get started."
            action={
              <button
                onClick={addProduct}
                className="text-sm font-semibold px-4 py-2 rounded-lg"
                style={{ color: "var(--v-cyan)", border: "0.5px solid var(--v-border)" }}
              >
                + Add first product
              </button>
            }
          />
        </div>
      ) : (
        <div className="space-y-3">
          {products.map((product) => (
            <ProductRow
              key={product.client_id}
              product={product}
              onChange={(patch) => updateProduct(product.client_id, patch)}
              onRemove={() => removeProduct(product.client_id)}
            />
          ))}
          <button
            onClick={addProduct}
            className="w-full text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
            style={{ color: "var(--v-cyan)", border: "1px dashed var(--v-border)" }}
          >
            + Add Product
          </button>
        </div>
      )}

      {products.length > 0 && missingCategoryCount > 0 && (
        <div className={`mt-5 ${warningBannerCls}`} style={warningBannerStyle}>
          <p className="text-xs" style={{ color: "var(--v-text-muted)" }}>
            <span className="font-semibold" style={{ color: "var(--v-amber)" }}>{missingCategoryCount} product{missingCategoryCount > 1 ? "s" : ""}</span>{" "}
            missing a category.
          </p>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// ProductRow — one card per product
// ─────────────────────────────────────────────────────────────────────
interface ProductRowProps {
  product: ProductDraft
  onChange: (patch: Partial<ProductDraft>) => void
  onRemove: () => void
}

function ProductRow({ product, onChange, onRemove }: ProductRowProps) {
  const handleTypeChange = (nextType: ProductDraft["product_type"]) => {
    onChange({
      product_type: nextType,
      category: nextType === "drink" ? product.category : null,
      food_type: nextType === "food" ? product.food_type : null,
    })
  }

  return (
    <div className={rowCardCls}>
      {/* Row 1: name | remove */}
      <div className="grid grid-cols-12 gap-3 mb-3">
        <div className="col-span-10">
          <Label>Product name</Label>
          <input
            className={inputCls}
            value={product.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. Moretti 33cl"
          />
        </div>
        <div className="col-span-2 flex items-end justify-end">
          <button
            onClick={onRemove}
            className="w-full h-[38px] flex items-center justify-center rounded-lg text-lg transition-colors"
            style={{ color: "var(--v-pink)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255, 61, 113, 0.08)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            aria-label={`Remove ${product.name || "this product"}`}
            title="Remove product"
          >
            ×
          </button>
        </div>
      </div>

      {/* Row 2: product type | category or food type */}
      <div className="grid grid-cols-12 gap-3 mb-3">
        <div className="col-span-6">
          <Label>Product type</Label>
          <select
            className={inputCls}
            value={product.product_type}
            onChange={(e) => handleTypeChange(e.target.value as ProductDraft["product_type"])}
          >
            {PRODUCT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        {product.product_type === "drink" && (
          <div className="col-span-6">
            <Label>Category</Label>
            <select
              className={inputCls}
              value={product.category ?? ""}
              onChange={(e) =>
                onChange({ category: (e.target.value || null) as ProductDraft["category"] })
              }
            >
              <option value="">— select —</option>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        )}
        {product.product_type === "food" && (
          <div className="col-span-6">
            <Label>Food type</Label>
            <select
              className={inputCls}
              value={product.food_type ?? ""}
              onChange={(e) =>
                onChange({ food_type: (e.target.value || null) as ProductDraft["food_type"] })
              }
            >
              <option value="">— select —</option>
              {FOOD_TYPES.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Row 3: unit | price */}
      <div className="grid grid-cols-12 gap-3 mb-3">
        <div className="col-span-6">
          <Label>Unit</Label>
          <select
            className={inputCls}
            value={product.unit}
            onChange={(e) => onChange({ unit: e.target.value as ProductDraft["unit"] })}
          >
            {UNITS.map((u) => (
              <option key={u.value} value={u.value}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-6">
          <Label>Price (€)</Label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={centsToEurosDisplay(product.default_price_cents)}
            onChange={(e) => onChange({ default_price_cents: eurosToCents(e.target.value) })}
            placeholder="8.50"
          />
        </div>
      </div>

      {/* Row 4: IVA | cauzione | tier */}
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-4">
          <Label>IVA (%)</Label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={pctToFractionDisplay(product.iva_pct)}
            onChange={(e) => {
              const raw = e.target.value.trim()
              const n = Number(raw)
              onChange({ iva_pct: raw === "" || !Number.isFinite(n) ? null : n / 100 })
            }}
            placeholder="10"
          />
        </div>
        <div className="col-span-4">
          <Label>Cauzione (€)</Label>
          <input
            className={inputCls}
            inputMode="decimal"
            value={product.cauzione_cents === null ? "" : centsToEurosDisplay(product.cauzione_cents)}
            onChange={(e) => {
              const raw = e.target.value.trim()
              onChange({ cauzione_cents: raw === "" ? null : eurosToCents(raw) })
            }}
            placeholder="0.00"
          />
        </div>
        {product.product_type === "drink" && (
          <div className="col-span-4">
            <Label>Tier (1–4)</Label>
            <input
              className={inputCls}
              type="number"
              min={1}
              max={4}
              value={product.tier_rank ?? ""}
              onChange={(e) => {
                const raw = e.target.value.trim()
                onChange({ tier_rank: raw === "" ? null : Math.max(1, Math.min(4, Math.floor(Number(raw) || 1))) })
              }}
              placeholder="auto"
            />
          </div>
        )}
      </div>
    </div>
  )
}
