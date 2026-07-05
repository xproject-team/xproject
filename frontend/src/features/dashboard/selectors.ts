/**
 * Pure selectors that transform raw backend API responses into the view-model
 * (BarKpi[]) that BarCard consumes.
 *
 * Why pure functions separated from hooks.ts:
 * - Testable in isolation (no React, no network)
 * - All the interesting math (aggregation, tier bucketing, status derivation)
 *   lives in one greppable place
 * - If the calculation needs to move to the backend later, it's a lift-and-shift
 *
 * Inputs are the raw shapes returned by the /bars, /bar-stock, /stock-transactions,
 * /products endpoints (see lib/mockData.ts for type defs).
 *
 * Output is a BarKpi[] — one per bar in the event — with every field BarCard
 * renders, plus explicit nulls for fields not yet computable (burn_rate etc.).
 */
import type {
  BarKpi,
  FoodItemCount,
  BarRow,
  BarStatus,
  BarStockRow,
  DrinksBreakdown,
  ProductRow,
  ProductTier,
  StockTransactionRow,
} from '@/lib/mockData'
import type { BurnRateRow } from '@/features/dashboard/hooks'

// ─── Status thresholds (stock % → healthy / warning / critical) ──────────────
// These mirror the visual thresholds used by the existing UI (BarCard.tsx
// uses >60 green, >30 yellow, else red for its progress bar color).
// Keeping the logic here so UI stays dumb and thresholds are reviewable.

const STATUS_THRESHOLDS = {
  healthy:  60,  // stock_pct > 60 → healthy
  warning:  30,  // stock_pct > 30 → warning; else critical
} as const

export function deriveStatus(stockPct: number, initialStock: number = -1): BarStatus {
  // When the bar has no allocation tracked (initial_stock=0), the percentage
  // is mathematically undefined and the 'critical' fallback below would scare
  // owners with a red label that means nothing. Treat as 'healthy' instead —
  // no stock to deplete means no stock concern. Real depletion warnings
  // still fire correctly once allocations exist.
  // The default of -1 preserves backward compatibility for callers that
  // haven't been updated to pass initialStock yet.
  if (initialStock === 0) return 'healthy'
  if (stockPct > STATUS_THRESHOLDS.healthy) return 'healthy'
  if (stockPct > STATUS_THRESHOLDS.warning) return 'warning'
  return 'critical'
}

// ─── Tier mapping: product.tier_rank (1..4) → UI tier letter (B/S/P/U) ──────
// Locked in backend Step 2 (Products catalog): tier_rank 1 = Basic,
// 2 = Standard, 3 = Premium, 4 = Ultra-premium.

function tierFromRank(rank: number | null): ProductTier | null {
  switch (rank) {
    case 1:  return 'B'
    case 2:  return 'S'
    case 3:  return 'P'
    case 4:  return 'U'
    default: return null
  }
}

const EMPTY_BREAKDOWN: DrinksBreakdown = { B: 0, S: 0, P: 0, U: 0 }

// ─── Main selector: build BarKpi[] from raw API responses ────────────────────

import type { BarAllocationSummary } from '@/features/event_storage/types'

export interface SelectorInput {
  bars:         BarRow[]
  barStock:     BarStockRow[]
  transactions: StockTransactionRow[]
  products:     ProductRow[]
  burnRates:    BurnRateRow[]
  /** Phase 2.5 dispatches. When present for a bar, override bar_stock
   *  totals (which lag for non-Slesh events). */
  allocations?: BarAllocationSummary[]
  /** event.food_revenue_share_pct from the live event; injected by DashboardPage */
  eventFoodRevenueSharePct?: number | null
  /** 2026-07-05: bar_id → fiscal gross revenue (euros, not cents) from
   *  event_orders. Food bars use this for revenue_cents display since they
   *  have no stock_transactions. When absent (or bar not in map), falls
   *  back to summing txAtBar as before. */
  foodFiscalRevenueByBarId?: Record<string, number>
}

export function selectBarKpis(input: SelectorInput): BarKpi[] {
  const { bars, barStock, transactions, products, burnRates, allocations, foodFiscalRevenueByBarId } = input
  // Phase 2.5 dispatch totals per bar — qty_total_allocated is a Decimal string.
  const allocTotalByBar = new Map<string, number>()
  for (const summary of allocations ?? []) {
    const total = summary.items.reduce(
      (s, it) => s + (parseFloat(it.qty_total_allocated) || 0),
      0,
    )
    allocTotalByBar.set(summary.bar_id, total)
  }

  // ── Index products by id for O(1) lookup during aggregation ──
  const productById = new Map<string, ProductRow>()
  for (const p of products) productById.set(p.id, p)

  // ── Filter transactions to PARENT rows only ──
  // Children (recipe ingredient decrements) share product_id with the
  // ingredient, not the drink, and carry price_cents=null. Counting them
  // would double-count sales.
  const parentTxs = transactions.filter(
    (t) => t.parent_transaction_id === null,
  )

  // ── Build one BarKpi per bar ──
  return bars.map((bar) => {
    // All stock rows at this bar (across every product allocated here)
    const stockAtBar = barStock.filter((s) => s.bar_id === bar.id)
    // Parent transactions at this bar (hoisted so food_items below can use it).
    const txAtBar = parentTxs.filter((t) => t.bar_id === bar.id)

    // Per-food-item counts for the food-bar card variant (Phase D-bis).
    // Food bars: list each item sold this event. Derived from transactions
    // (NOT bar_stock) — food trucks are third-party and we don't track
    // their inventory, so 'remaining' is always 0 / unknown. Group all
    // FOOD-product txs at this bar by product_id and sum qty for 'sold'.
    // Drink bars get [].
    const food_items: FoodItemCount[] =
      bar.bar_type === 'food'
        ? (() => {
            const soldByProduct = new Map<string, { name: string; sold: number }>()
            for (const tx of txAtBar) {
              const p = productById.get(tx.product_id)
              if (p?.product_type !== 'food') continue
              const existing = soldByProduct.get(tx.product_id)
              const qty = typeof tx.qty === 'string' ? parseFloat(tx.qty) : (tx.qty ?? 0)
              if (existing) {
                existing.sold += qty
              } else {
                soldByProduct.set(tx.product_id, {
                  name: p.name ?? 'Unknown item',
                  sold: qty,
                })
              }
            }
            return Array.from(soldByProduct.values())
              .map((v) => ({ name: v.name, sold: v.sold, remaining: 0 }))
              .sort((a, b) => b.sold - a.sold)
          })()
        : []


    // ── Stock aggregates ──
    // Phase 2.5: when this bar has allocations (Inventory dispatches), they
    // are the source of truth. Legacy bar_stock only updates from Slesh sync
    // and lags for sim/dispatched-only events. We approximate consumption as
    // 1 unit per parent transaction (matches Slesh qty=1 convention).
    const allocTotal = allocTotalByBar.get(bar.id) ?? 0
    const stockFromBarStock_initial = stockAtBar.reduce(
      (sum, s) => sum + s.allocated_qty,
      0,
    )
    const stockFromBarStock_current = stockAtBar.reduce(
      (sum, s) => sum + s.current_qty,
      0,
    )
    const initial_stock = allocTotal > 0 ? allocTotal : stockFromBarStock_initial
    const current_stock = allocTotal > 0
      ? Math.max(allocTotal - txAtBar.length, 0)
      : stockFromBarStock_current
    const stock_pct = initial_stock === 0
      ? 0
      : Math.round((current_stock / initial_stock) * 100)

    // ── Revenue: sum of parent transaction price_cents ──
    // 2026-07-05: food bars have no stock_transactions (no recipes),
    // so their revenue is €0 unless we use the fiscal totals from
    // event_orders. When a fiscal map is provided, use it for food bars.
    // Drinks bars keep the stock-transactions rollup unchanged.
    const stockRevenue = txAtBar.reduce(
      (sum, t) => sum + (t.price_cents ?? 0),
      0,
    )
    const fiscalEurForBar = foodFiscalRevenueByBarId?.[bar.id]
    const revenue_cents = bar.bar_type === 'food' && fiscalEurForBar !== undefined
      ? Math.round(fiscalEurForBar * 100)
      : stockRevenue

    // ── Drinks breakdown + total ──
    // drinks_sold counts every transaction on a DRINK product (definitive
    // truth from product_type). The tier breakdown is an OPTIONAL refinement:
    // a drink without tier_rank still counts toward drinks_sold but doesn't
    // land in any breakdown bucket. This decouples the headline count from
    // the catalog-curation state of tier_rank, which is often NULL on
    // freshly-seeded menus (Slesh sends names, tier_rank is set later by
    // Omar in the catalog).
    const drinks_breakdown: DrinksBreakdown = { ...EMPTY_BREAKDOWN }
    let drinks_sold = 0
    for (const tx of txAtBar) {
      const product = productById.get(tx.product_id)
      if (product?.product_type !== 'drink') continue
      drinks_sold += 1
      const tier = tierFromRank(product?.tier_rank ?? null)
      if (tier) {
        drinks_breakdown[tier] += 1
      }
    }

    // Burn-rate aggregates
    const brAtBar = burnRates.filter((r) => r.bar_id === bar.id)
    const bar_burn_rate = brAtBar.length === 0
      ? null
      : brAtBar.reduce((sum, r) => sum + parseFloat(r.burn_rate_per_hour), 0)
    const ttdCandidates = brAtBar
      .map((r) => r.time_to_depletion_min === null ? null : parseFloat(r.time_to_depletion_min))
      .filter((v): v is number => v !== null && v > 0)
    const bar_ttd = ttdCandidates.length === 0 ? null : Math.min(...ttdCandidates)

    return {
      // Real fields
      id:               bar.id,
      name:             bar.name,
      status:           deriveStatus(stock_pct, initial_stock),
      revenue_cents,
      drinks_sold,
      drinks_breakdown,
      current_stock,
      initial_stock,
      stock_pct,
      bar_type:         bar.bar_type,
      food_items,
      auto_created:     bar.auto_created ?? false,
      slesh_negozio_id: bar.slesh_negozio_id ?? null,
      // Placeholder fields (v1.1)
      burn_rate:            bar_burn_rate,
      burn_trend:           null,
      time_to_depletion_min: bar_ttd,
      staff_count:          null,
      last_alert:           null,
      // ── Phase 2 (Jun 21 2026): real device data from BarRow ──
      devices:        bar.devices ?? [],
      devices_total:  (bar.devices ?? []).length,
      devices_active: bar.devices_active ?? 0,
      // Wired Jun 21 2026 (Phase 4 step 1): replaces hardcoded 30%.
      food_revenue_share_pct: input.eventFoodRevenueSharePct ?? null,
    }
  })
}

// ─── Aggregate selector: totals across all bars for the KPI strip ────────────

export interface DashboardTotals {
  totalRevenueCents: number
  totalDrinksSold:   number
  tierTotals:        DrinksBreakdown
}

export function selectDashboardTotals(bars: BarKpi[]): DashboardTotals {
  return bars.reduce<DashboardTotals>(
    (acc, b) => ({
      totalRevenueCents: acc.totalRevenueCents + b.revenue_cents,
      totalDrinksSold:   acc.totalDrinksSold + b.drinks_sold,
      tierTotals: {
        B: acc.tierTotals.B + b.drinks_breakdown.B,
        S: acc.tierTotals.S + b.drinks_breakdown.S,
        P: acc.tierTotals.P + b.drinks_breakdown.P,
        U: acc.tierTotals.U + b.drinks_breakdown.U,
      },
    }),
    {
      totalRevenueCents: 0,
      totalDrinksSold:   0,
      tierTotals:        { ...EMPTY_BREAKDOWN },
    },
  )
}
