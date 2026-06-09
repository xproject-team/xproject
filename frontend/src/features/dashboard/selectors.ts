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

export function deriveStatus(stockPct: number): BarStatus {
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

export interface SelectorInput {
  bars:         BarRow[]
  barStock:     BarStockRow[]
  transactions: StockTransactionRow[]
  products:     ProductRow[]
  burnRates:    BurnRateRow[]
}

export function selectBarKpis(input: SelectorInput): BarKpi[] {
  const { bars, barStock, transactions, products, burnRates } = input

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

    // Per-food-item counts for the food-bar card variant (Phase D-bis).
    // Food bars list each item (sold = allocated - current); drink bars get [].
    const food_items: FoodItemCount[] =
      bar.bar_type === 'food'
        ? stockAtBar
            .filter((s) => productById.get(s.product_id)?.product_type === 'food')
            .map((s) => {
              const p = productById.get(s.product_id)
              return {
                name: p?.name ?? 'Unknown item',
                sold: Math.max(0, s.allocated_qty - s.current_qty),
                remaining: s.current_qty,
              }
            })
            .sort((a, b) => b.sold - a.sold)
        : []

    // Parent transactions at this bar
    const txAtBar = parentTxs.filter((t) => t.bar_id === bar.id)

    // ── Stock aggregates ──
    const initial_stock = stockAtBar.reduce(
      (sum, s) => sum + s.allocated_qty,
      0,
    )
    const current_stock = stockAtBar.reduce(
      (sum, s) => sum + s.current_qty,
      0,
    )
    const stock_pct = initial_stock === 0
      ? 0
      : Math.round((current_stock / initial_stock) * 100)

    // ── Revenue: sum of parent transaction price_cents ──
    const revenue_cents = txAtBar.reduce(
      (sum, t) => sum + (t.price_cents ?? 0),
      0,
    )

    // ── Drinks breakdown + total: tier-classified products only ──
    // The KPI is labelled "DRINKS SOLD", so it must count only transactions
    // on drinks.  A drink is any product whose catalog row has tier_rank set
    // (1=Basic, 2=Standard, 3=Premium, 4=Ultra).  Non-drink transactions
    // (food, supplies) are excluded.  Single pass guarantees that drinks_sold
    // equals the sum of breakdown buckets by construction.
    const drinks_breakdown: DrinksBreakdown = { ...EMPTY_BREAKDOWN }
    let drinks_sold = 0
    for (const tx of txAtBar) {
      const product = productById.get(tx.product_id)
      const tier = tierFromRank(product?.tier_rank ?? null)
      if (tier) {
        drinks_breakdown[tier] += 1
        drinks_sold           += 1
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
      status:           deriveStatus(stock_pct),
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
