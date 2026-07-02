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
import type { PredictedCurvePoint } from '@/features/predictions/useRevenueForecast'

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


// ────────────────────────────────────────────────────────────────────────────
//
// Stacked-bar-per-product chart (Hesam-requested, replaces 4-category lines
// for drink bars). Each time bucket renders as a stacked bar where each
// segment is one drink product's revenue IN THAT BUCKET (incremental, not
// cumulative). Tooltip surfaces exact revenue + units per drink for that
// bucket so Omar can see WHICH drinks drove a peak and WHEN. Builds a
// productOrder array (rank-by-total-revenue desc) so the component renders
// <Bar> elements in the correct stack order.
//
// ────────────────────────────────────────────────────────────────────────────

export interface StackedBarChartPoint {
  time_label: string
  time_ms:    number
  total:      number  // total euros in this bucket
  __units:    Record<string, number>  // sidecar: per-product units (for tooltip)
  __names:    Record<string, string>  // sidecar: per-product display names
  // Plus dynamic [productId]: number entries — euros per product in this bucket.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any
}

export interface BuildStackedBarInput {
  transactions:      StockTransactionRow[]
  barId:             string
  eventStartMs:      number
  nowMs:             number
  productNameById:   Record<string, string>
  /** Subset of product IDs to include (e.g. drinks only). Undefined = all. */
  allowedProductIds?: Set<string>
}

export interface StackedBarResult {
  points:       StackedBarChartPoint[]
  /** Product IDs in rank order (by total revenue desc) — render Bars in this order */
  productOrder: string[]
}

export function buildStackedBarPerProduct(
  input: BuildStackedBarInput,
): StackedBarResult {
  const { transactions, barId, eventStartMs, nowMs, productNameById, allowedProductIds } = input

  const relevant = transactions
    .filter((t) =>
      t.bar_id === barId &&
      t.parent_transaction_id === null &&
      t.price_cents !== null &&
      (allowedProductIds === undefined || allowedProductIds.has(t.product_id)),
    )
    .map((t) => ({
      ts:        new Date(t.created_at).getTime(),
      productId: t.product_id,
      cents:     t.price_cents as number,
      qty:       t.qty,
    }))
    .sort((a, b) => a.ts - b.ts)

  // Compute total per product to determine rank order (desc by revenue).
  // The component renders <Bar> elements in this order so the visual stack
  // is consistent across bars and the top-seller is always the bottom of
  // the stack.
  const totalCents = new Map<string, number>()
  for (const r of relevant) {
    totalCents.set(r.productId, (totalCents.get(r.productId) ?? 0) + r.cents)
  }
  const productOrder = [...totalCents.entries()]
    .filter(([, c]) => c > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => id)

  // Bucketing — same ladder as the multi-line chart for consistency.
  const bucketMin    = pickBucketMinutes(nowMs - eventStartMs)
  const bucketMs     = bucketMin * 60 * 1000
  const alignedStart = floorToBucket(eventStartMs, bucketMs)
  const alignedEnd   = floorToBucket(nowMs, bucketMs) + bucketMs

  const points: StackedBarChartPoint[] = []
  let txIdx = 0

  for (let bs = alignedStart; bs < alignedEnd; bs += bucketMs) {
    const be = bs + bucketMs
    const bucketRev:   Record<string, number> = {}
    const bucketUnits: Record<string, number> = {}

    while (txIdx < relevant.length && relevant[txIdx].ts < be) {
      const r = relevant[txIdx]
      bucketRev[r.productId]   = (bucketRev[r.productId]   ?? 0) + r.cents
      bucketUnits[r.productId] = (bucketUnits[r.productId] ?? 0) + r.qty
      txIdx += 1
    }

    let total = 0
    const point: StackedBarChartPoint = {
      time_label: formatTime(bs),
      time_ms:    bs,
      total:      0,
      __units:    {},
      __names:    {},
    }

    for (const id of productOrder) {
      const cents = bucketRev[id] ?? 0
      if (cents > 0) {
        const euros        = Math.round(cents / 100)
        point[id]          = euros
        point.__units[id]  = bucketUnits[id] ?? 0
        point.__names[id]  = productNameById[id] ?? id.slice(0, 8)
        total += euros
      }
    }
    point.total = total

    points.push(point)
  }

  return { points, productOrder }
}


// ────────────────────────────────────────────────────────────────────────────
//
// Phase E — merge the Phase D nowcast's predicted_curve into an
// event-total ChartPoint[] (see buildEventRevenuePoints above).
//
// ────────────────────────────────────────────────────────────────────────────

/**
 * Linear interpolation over a sorted set of (hour_offset, cumulative
 * revenue) points. Clamps to the first/last point outside the curve's
 * own range (mirrors the backend predictor's np.interp behavior).
 */
function interpolateCurveAtHour(
  curve: PredictedCurvePoint[],
  hourOffset: number,
): number | null {
  if (curve.length === 0) return null
  if (hourOffset <= curve[0].hour_offset) return curve[0].cumulative_revenue_eur
  const last = curve[curve.length - 1]
  if (hourOffset >= last.hour_offset) return last.cumulative_revenue_eur

  for (let i = 0; i < curve.length - 1; i++) {
    const a = curve[i]
    const b = curve[i + 1]
    if (hourOffset >= a.hour_offset && hourOffset <= b.hour_offset) {
      const t = (hourOffset - a.hour_offset) / (b.hour_offset - a.hour_offset)
      return a.cumulative_revenue_eur + t * (b.cumulative_revenue_eur - a.cumulative_revenue_eur)
    }
  }
  return null
}

/**
 * Overlay the forecast's predicted_curve onto an event-total
 * ChartPoint[], filling in `predicted` for buckets at or after "now"
 * (hourOffsetFromStart). Buckets before that are left untouched — the
 * actual line already covers the past, and predicted_curve itself only
 * contains hours strictly after hour_offset_from_start (Phase D's
 * schema deliberately excludes the current point — see
 * backend/app/modules/predictions/nowcast/predictor.py's predict()).
 *
 * A synthetic bridge point (hourOffsetFromStart, currentRevenueEur) is
 * prepended before interpolating so the dashed predicted line starts
 * exactly where the solid actual line ends, instead of jumping to the
 * next 1-hour grid point.
 *
 * hourOffsetFromStart / currentRevenueEur are computed by the backend
 * relative to the event's actual first REVENUE transaction, while
 * eventStartMs here is event.started_at (an admin timestamp that can
 * differ from the first sale by a few minutes) — matching hour_offset
 * against elapsed-time-since-eventStartMs is a deliberate, small
 * approximation: the Phase D response doesn't expose the raw
 * first-transaction timestamp, only the pre-computed offset.
 */
export function mergePredictedCurve(
  points:              ChartPoint[],
  predictedCurve:      PredictedCurvePoint[] | undefined,
  eventStartMs:        number,
  currentRevenueEur:   number | undefined,
  hourOffsetFromStart: number | undefined,
): ChartPoint[] {
  if (!predictedCurve?.length || hourOffsetFromStart === undefined || currentRevenueEur === undefined) {
    return points
  }

  const bridgedCurve: PredictedCurvePoint[] = [
    { hour_offset: hourOffsetFromStart, cumulative_revenue_eur: currentRevenueEur },
    ...predictedCurve,
  ]

  return points.map((point) => {
    const elapsedHr = (point.time_ms - eventStartMs) / 3600_000
    if (elapsedHr < hourOffsetFromStart) return point
    const predicted = interpolateCurveAtHour(bridgedCurve, elapsedHr)
    return predicted === null ? point : { ...point, predicted: Math.round(predicted) }
  })
}

