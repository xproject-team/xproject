/**
 * Adaptive time-bucket math for the Revenue chart in BarDetailOverlay.
 *
 * Pure functions, no React, no network. Testable in isolation.
 *
 * Rationale (locked April 17 2026):
 * - Minute-by-minute is too noisy for ops dashboards (6-hr event = 360 pts)
 * - Fixed buckets fail at either short OR long event durations
 * - Adaptive = auto-pick bucket size based on elapsed-since-start time
 *
 * Bucket ladder:
 *   0-30 min elapsed  ->  1-min buckets  (early event, every tx matters)
 *   30-120 min        ->  5-min buckets
 *   2-6 hrs           ->  15-min buckets
 *   6+ hrs            ->  30-min buckets
 *
 * Cumulative revenue (running total) is more readable than per-bucket revenue,
 * because revenue should monotonically climb - easier to compare to prediction.
 */
import type { StockTransactionRow } from '@/lib/mockData'

export interface ChartPoint {
  time_label:  string   // "19:00" - axis label
  time_ms:     number   // unix ms - for sorting and tooltips
  actual:      number   // cumulative actual revenue in euros, as of this bucket
  predicted:   number | null   // null until ML prediction backend ships
}

export function pickBucketMinutes(elapsedMs: number): 1 | 5 | 15 | 30 {
  const elapsedMin = elapsedMs / 60000
  if (elapsedMin < 30)  return 1
  if (elapsedMin < 120) return 5
  if (elapsedMin < 360) return 15
  return 30
}

function floorToBucket(ts: number, bucketMs: number): number {
  return Math.floor(ts / bucketMs) * bucketMs
}

function formatTime(ms: number): string {
  const d = new Date(ms)
  const h = d.getHours().toString().padStart(2, '0')
  const m = d.getMinutes().toString().padStart(2, '0')
  return h + ':' + m
}

export interface BuildChartInput {
  transactions: StockTransactionRow[]
  barId:        string
  eventStartMs: number
  nowMs:        number
}

/**
 * Build cumulative revenue points for a single bar.
 *
 * Algorithm:
 *   1. Filter transactions to parent-only (price_cents != null) at this bar
 *   2. Pick bucket size from elapsed time
 *   3. For each bucket from eventStart to now, compute cumulative revenue
 *      up through that bucket (includes all transactions with created_at <= bucket_end)
 *   4. Return one point per bucket, even empty ones (flat line reads honest)
 */
export function buildRevenuePoints(input: BuildChartInput): ChartPoint[] {
  const { transactions, barId, eventStartMs, nowMs } = input

  const bucketMin = pickBucketMinutes(nowMs - eventStartMs)
  const bucketMs  = bucketMin * 60 * 1000

  // Align event start to bucket boundary (prevents jittery first-bucket labels)
  const alignedStart = floorToBucket(eventStartMs, bucketMs)
  // End at current bucket (or +1 to include partial current bucket)
  const alignedEnd = floorToBucket(nowMs, bucketMs) + bucketMs

  // Parent-transactions at this bar, sorted by created_at ascending
  const relevant = transactions
    .filter((t) =>
      t.bar_id === barId &&
      t.parent_transaction_id === null &&
      t.price_cents !== null,
    )
    .map((t) => ({
      ts: new Date(t.created_at).getTime(),
      cents: t.price_cents as number,
    }))
    .sort((a, b) => a.ts - b.ts)

  const points: ChartPoint[] = []
  let cumulativeCents = 0
  let txIndex = 0

  for (let bucket_start = alignedStart; bucket_start < alignedEnd; bucket_start += bucketMs) {
    const bucket_end = bucket_start + bucketMs
    // Consume all transactions whose created_at falls in this bucket
    while (txIndex < relevant.length && relevant[txIndex].ts < bucket_end) {
      cumulativeCents += relevant[txIndex].cents
      txIndex += 1
    }
    points.push({
      time_label:  formatTime(bucket_start),
      time_ms:     bucket_start,
      actual:      Math.round(cumulativeCents / 100),
      predicted:   null,
    })
  }

  return points
}

// ─────────────────────────────────────────────────────────────────────────
// DASH.3 additions — multi-line per-bar chart + event-total chart
// ─────────────────────────────────────────────────────────────────────────
// New ChartPoint variant for multi-line series. Each point carries:
//   - a value per category (key = category name, value = cumulative € as of bucket)
//   - a total = sum of all categories
// The 5 lines on the chart are: beer / cocktails / premium_cocktails / wine
// / total. Categories with zero sales for the whole event are not added
// (chart stays uncluttered).

export interface MultiLineChartPoint {
  time_label: string
  time_ms:    number
  total:      number
  // Per-category cumulative revenue in euros. Optional because not every
  // bar sells every category. Recharts renders missing keys as gaps.
  beer?:              number
  cocktails?:         number
  premium_cocktails?: number
  wine?:              number
  food?:              number
}

export interface BuildMultiLineInput {
  transactions:        StockTransactionRow[]
  barId:               string
  eventStartMs:        number
  nowMs:               number
  // Map of product_id → category string ("beer" | "cocktails" |
  // "premium_cocktails" | "wine" | "food" | "other"). Caller computes
  // this via category-resolver.ts before calling.
  categoryByProductId: Record<string, string>
}

/**
 * Build cumulative revenue points per category for a single bar.
 *
 * Returns one point per bucket; each point has up to 5 numeric fields
 * (beer / cocktails / premium_cocktails / wine + total). Categories with
 * no sales during the event are omitted from every point.
 *
 * Algorithm mirrors buildRevenuePoints:
 *   1. Filter to parent-only revenue txns at this bar
 *   2. Group running totals by category
 *   3. One point per bucket with the running totals snapshot
 */
export function buildMultiLineBarRevenuePoints(
  input: BuildMultiLineInput,
): MultiLineChartPoint[] {
  const { transactions, barId, eventStartMs, nowMs, categoryByProductId } = input

  const bucketMin = pickBucketMinutes(nowMs - eventStartMs)
  const bucketMs  = bucketMin * 60 * 1000
  const alignedStart = floorToBucket(eventStartMs, bucketMs)
  const alignedEnd   = floorToBucket(nowMs, bucketMs) + bucketMs

  // Only the 4 drink buckets are charted on bar cards. Food + other are
  // counted in "total" but not drawn as separate lines (less visual noise).
  const VISIBLE_CATEGORIES = ['beer', 'cocktails', 'premium_cocktails', 'wine'] as const

  const relevant = transactions
    .filter((t) =>
      t.bar_id === barId &&
      t.parent_transaction_id === null &&
      t.price_cents !== null,
    )
    .map((t) => ({
      ts:       new Date(t.created_at).getTime(),
      cents:    t.price_cents as number,
      category: categoryByProductId[t.product_id] ?? 'other',
    }))
    .sort((a, b) => a.ts - b.ts)

  // Running cumulative cents per category + total
  const running: Record<string, number> = {
    beer: 0, cocktails: 0, premium_cocktails: 0, wine: 0, food: 0, other: 0,
  }

  const points: MultiLineChartPoint[] = []
  let txIndex = 0

  for (let bucket_start = alignedStart; bucket_start < alignedEnd; bucket_start += bucketMs) {
    const bucket_end = bucket_start + bucketMs

    while (txIndex < relevant.length && relevant[txIndex].ts < bucket_end) {
      const r = relevant[txIndex]
      if (r.category in running) running[r.category] += r.cents
      else running.other += r.cents
      txIndex += 1
    }

    const totalCents =
      running.beer + running.cocktails + running.premium_cocktails +
      running.wine + running.food + running.other

    const point: MultiLineChartPoint = {
      time_label: formatTime(bucket_start),
      time_ms:    bucket_start,
      total:      Math.round(totalCents / 100),
    }
    // Only attach a category key if that category has ANY sales.
    // Avoids rendering a flat-zero line for categories the bar doesn't sell.
    for (const cat of VISIBLE_CATEGORIES) {
      if (running[cat] > 0) {
        point[cat] = Math.round(running[cat] / 100)
      }
    }
    points.push(point)
  }

  return points
}


export interface BuildEventTotalInput {
  transactions: StockTransactionRow[]
  eventStartMs: number
  nowMs:        number
}

/**
 * Build cumulative event-total revenue points (across ALL bars).
 *
 * Same algorithm as buildRevenuePoints but without the barId filter.
 * Used by the big chart at the top of the dashboard. The `predicted`
 * field stays null until MLPredictor lands in Phase 2.
 */
export function buildEventRevenuePoints(input: BuildEventTotalInput): ChartPoint[] {
  const { transactions, eventStartMs, nowMs } = input

  const bucketMin = pickBucketMinutes(nowMs - eventStartMs)
  const bucketMs  = bucketMin * 60 * 1000
  const alignedStart = floorToBucket(eventStartMs, bucketMs)
  const alignedEnd   = floorToBucket(nowMs, bucketMs) + bucketMs

  const relevant = transactions
    .filter((t) =>
      t.parent_transaction_id === null &&
      t.price_cents !== null,
    )
    .map((t) => ({
      ts:    new Date(t.created_at).getTime(),
      cents: t.price_cents as number,
    }))
    .sort((a, b) => a.ts - b.ts)

  const points: ChartPoint[] = []
  let cumulativeCents = 0
  let txIndex = 0

  for (let bucket_start = alignedStart; bucket_start < alignedEnd; bucket_start += bucketMs) {
    const bucket_end = bucket_start + bucketMs
    while (txIndex < relevant.length && relevant[txIndex].ts < bucket_end) {
      cumulativeCents += relevant[txIndex].cents
      txIndex += 1
    }
    points.push({
      time_label: formatTime(bucket_start),
      time_ms:    bucket_start,
      actual:     Math.round(cumulativeCents / 100),
      predicted:  null,  // wired when MLPredictor lands
    })
  }
  return points
}
