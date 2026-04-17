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
