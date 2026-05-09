/**
 * Inventory page selectors — pure functions that turn raw backend rows
 * (BarRow + BarStockRow + ProductRow) into the view model the
 * InventoryPage table consumes.
 *
 * Why a separate selector from Dashboard:
 *   Dashboard rolls everything UP to the bar level (one BarKpi per bar).
 *   Inventory shows the per-product breakdown — one row per
 *   (bar, product) pair. Different aggregation, different selector.
 *
 * Reuses the same dashboardKeys hooks (useBarsForEvent, useBarStockForEvent,
 * useAllProducts) so we don't duplicate fetch logic.
 */
import type { BarRow, BarStockRow, ProductRow } from '@/lib/mockData'

// ─── View model types — same shape the legacy mock used ──────────────────
// Keeping these field names identical to the old MOCK_BARS / MOCK_PRODUCTS
// so the rest of InventoryPage.tsx renders unchanged.

export type ProductCategory = 'Spirits' | 'Beer' | 'Wine' | 'Mixers' | 'Other'
export type ProductStatus   = 'healthy' | 'warning' | 'critical' | 'depleted'
export type BarStatus       = 'healthy' | 'warning' | 'critical'

export interface InventoryBar {
  id:             string
  name:           string
  status:         BarStatus
  current_stock:  number  // sum of current_qty across all products at this bar
  initial_stock:  number  // sum of allocated_qty across all products at this bar
}

export interface InventoryProduct {
  id:                          string  // composite: barId__productId (unique row key)
  bar_id:                      string
  product_name:                string
  category:                    ProductCategory
  current_stock:               number
  initial_stock:               number
  reorder_level:               number  // not in backend → 0 (rendered as "—")
  status:                      ProductStatus
  consumption_rate:            number  // not in backend yet → 0 (rendered as "—")
  estimated_depletion_minutes: number  // not in backend yet → 999 (renders as "—")
  unit_price:                  number  // from product.default_price_cents / 100
}

// ─── Status thresholds (mirror the Dashboard's deriveStatus) ─────────────

function deriveProductStatus(current: number, initial: number): ProductStatus {
  if (initial === 0) return 'depleted'
  if (current === 0) return 'depleted'
  const pct = (current / initial) * 100
  if (pct > 60) return 'healthy'
  if (pct > 30) return 'warning'
  return 'critical'
}

function deriveBarStatus(current: number, initial: number): BarStatus {
  if (initial === 0) return 'critical'
  const pct = (current / initial) * 100
  if (pct > 60) return 'healthy'
  if (pct > 30) return 'warning'
  return 'critical'
}

// ─── Map backend product.category (free text) → UI ProductCategory ───────
// Backend categories are free-form (whisky, gin, vodka, beer, wine, ...).
// We bucket them into the 5 UI categories. Falls back to 'Other'.

function mapCategory(raw: string | null): ProductCategory {
  if (!raw) return 'Other'
  const c = raw.toLowerCase()
  if (/(whisk|gin|vodka|rum|tequila|bourbon|spirit|liquor)/.test(c)) return 'Spirits'
  if (/beer/.test(c)) return 'Beer'
  if (/(wine|prosecco|champagne|sparkling)/.test(c)) return 'Wine'
  if (/(mixer|tonic|soda|juice|cola)/.test(c)) return 'Mixers'
  return 'Other'
}

// ─── Main selectors ──────────────────────────────────────────────────────

export interface SelectorInput {
  bars:     BarRow[]
  barStock: BarStockRow[]
  products: ProductRow[]
}

export function selectInventoryBars(input: SelectorInput): InventoryBar[] {
  const { bars, barStock } = input
  return bars.map((bar) => {
    const stockAtBar = barStock.filter((s) => s.bar_id === bar.id)
    const current_stock = stockAtBar.reduce((sum, s) => sum + s.current_qty, 0)
    const initial_stock = stockAtBar.reduce((sum, s) => sum + s.allocated_qty, 0)
    return {
      id:            bar.id,
      name:          bar.name,
      current_stock,
      initial_stock,
      status:        deriveBarStatus(current_stock, initial_stock),
    }
  })
}

export function selectInventoryProducts(input: SelectorInput): InventoryProduct[] {
  const { barStock, products } = input

  const productById = new Map<string, ProductRow>()
  for (const p of products) productById.set(p.id, p)

  return barStock.map((s) => {
    const product = productById.get(s.product_id)
    return {
      id:                          `${s.bar_id}__${s.product_id}`,
      bar_id:                      s.bar_id,
      product_name:                product?.name ?? '(unknown product)',
      category:                    mapCategory(product?.category ?? null),
      current_stock:               s.current_qty,
      initial_stock:               s.allocated_qty,
      reorder_level:               0,
      status:                      deriveProductStatus(s.current_qty, s.allocated_qty),
      consumption_rate:            0,
      estimated_depletion_minutes: 999,
      unit_price:                  (product?.default_price_cents ?? 0) / 100,
    }
  })
}
