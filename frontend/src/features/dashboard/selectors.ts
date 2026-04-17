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
  BarRow,
  BarStatus,
  BarStockRow,
  DrinksBreakdown,
  ProductRow,
  ProductTier,
  StockTransactionRow,
} from '@/lib/mockData'

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
}

export function selectBarKpis(input: SelectorInput): BarKpi[] {
  const { bars, barStock, transactions, products } = input

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

    // ── Drinks sold: count of parent transactions ──
    const drinks_sold = txAtBar.length

    // ── Drinks breakdown: bucket by product's tier_rank ──
    const drinks_breakdown: DrinksBreakdown = { ...EMPTY_BREAKDOWN }
    for (const tx of txAtBar) {
      const product = productById.get(tx.product_id)
      const tier = tierFromRank(product?.tier_rank ?? null)
      if (tier) drinks_breakdown[tier] += 1
    }

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
      // Placeholder fields (v1.1)
      burn_rate:            null,
      burn_trend:           null,
      time_to_depletion_min: null,
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
