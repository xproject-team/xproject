/**
 * BarCategoryBreakdown + BarTopDrinks — DASH.6.
 *
 * Renders the redesigned Drinks Breakdown section inside the bar
 * detail overlay. Replaces the OLD 4 tier tiles
 * (Basic / Standard / Premium / Ultra) with:
 *
 *   1. 4+1 category bucket tiles (beer / cocktails / premium_cocktails
 *      / wine / food) showing units + euro revenue.
 *   2. A top-5 drinks list ranked by units, each labeled with its
 *      granular category (e.g. "Cocktail signature -> premium_cocktail").
 *
 * Both components consume the same backend payload (one row from
 * EventBarCategoryTotalsResponse.bars[]). The parent fetches once via
 * useBarCategoryTotals and finds the row by bar_id before passing it
 * in. Pure presentational — no hooks here, easy to unit-test.
 *
 * Locked May 27 2026 with Hesam.
 */
import type {
  BarCategoryBucketDTO,
  BarCategoryTotalsDTO,
  BarTopDrinkDTO,
} from '@/features/dashboard/hooks'


// ─── Color palette ──────────────────────────────────────────────────
// Matches the BarMiniChart colors so the visual vocabulary stays
// consistent across the dashboard.
const _BUCKET_COLOR: Record<BarCategoryBucketDTO['bucket'], string> = {
  beer:              '#C49A2A',
  cocktails:         '#C2185B',
  premium_cocktails: '#6A1B9A',
  wine:              '#8B0000',
  food:              '#558B2F',
}

const _BUCKET_LABEL: Record<BarCategoryBucketDTO['bucket'], string> = {
  beer:              'Beer',
  cocktails:         'Cocktails',
  premium_cocktails: 'Premium',
  wine:              'Wine',
  food:              'Food',
}

// Granular category -> rolled-up bucket (for top-5 drinks color tag)
const _GRANULAR_TO_BUCKET: Record<string, BarCategoryBucketDTO['bucket'] | 'other'> = {
  beer_bottle:      'beer',
  beer_draft:       'beer',
  basic_cocktail:   'cocktails',
  cocktails:        'cocktails',
  premium_cocktail: 'premium_cocktails',
  premium_cocktails:'premium_cocktails',
  wine_red:         'wine',
  wine_white:       'wine',
  wine_sparkling:   'wine',
  wine:             'wine',
}

function _bucketFor(granular: string): BarCategoryBucketDTO['bucket'] | 'other' {
  return _GRANULAR_TO_BUCKET[granular] ?? 'other'
}

function _formatEur(value: string | number): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  if (!Number.isFinite(n) || n === 0) return '€0'
  if (n >= 1000) return '€' + (n / 1000).toFixed(1) + 'k'
  return '€' + Math.round(n).toLocaleString()
}


// ─────────────────────────────────────────────────────────────────────
// BarCategoryBreakdown — the 4+1 tile grid
// ─────────────────────────────────────────────────────────────────────

interface BarCategoryBreakdownProps {
  /** One bar\'s slice of the bar-category-totals response. */
  bar: BarCategoryTotalsDTO | null
}

export function BarCategoryBreakdown({ bar }: BarCategoryBreakdownProps) {
  if (!bar || bar.categories.length === 0) {
    return (
      <p className="text-sm text-[#A0AEC0] italic">
        No sales yet by category.
      </p>
    )
  }

  // Always render the 5 buckets in a stable order, even if a bar has
  // no sales in some of them (Omar wants the same layout on every card).
  const ORDER: BarCategoryBucketDTO['bucket'][] = [
    'beer', 'cocktails', 'premium_cocktails', 'wine', 'food',
  ]
  const byBucket = new Map(bar.categories.map((c) => [c.bucket, c]))

  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
      {ORDER.map((b) => {
        const row = byBucket.get(b)
        const units = row?.units ?? 0
        const rev = row?.revenue_eur ?? '0'
        const isEmpty = units === 0
        return (
          <div
            key={b}
            className={[
              'border rounded-lg px-3 py-2 text-center',
              isEmpty
                ? 'bg-[#F7FAFC] border-[#E2E8F0] text-[#A0AEC0]'
                : 'bg-white border-[#E2E8F0]',
            ].join(' ')}
          >
            <p
              className="text-[10px] uppercase tracking-wide font-semibold"
              style={{ color: isEmpty ? '#A0AEC0' : _BUCKET_COLOR[b] }}
            >
              {_BUCKET_LABEL[b]}
            </p>
            <p className="text-lg font-bold mt-0.5 text-[#1A202C]">{units}</p>
            <p className="text-[11px] text-[#4A5568]">{_formatEur(rev)}</p>
          </div>
        )
      })}
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────
// BarTopDrinks — top 5 drinks ranked by units
// ─────────────────────────────────────────────────────────────────────

interface BarTopDrinksProps {
  bar: BarCategoryTotalsDTO | null
}

export function BarTopDrinks({ bar }: BarTopDrinksProps) {
  if (!bar || bar.top_5_drinks.length === 0) {
    return (
      <p className="text-sm text-[#A0AEC0] italic">
        No drink sales yet to rank.
      </p>
    )
  }

  return (
    <div className="space-y-1.5">
      {bar.top_5_drinks.map((d: BarTopDrinkDTO, rank) => {
        const bucket = _bucketFor(d.category)
        const color = bucket === 'other' ? '#A0AEC0' : _BUCKET_COLOR[bucket]
        return (
          <div
            key={d.product_name + rank}
            className="flex items-center gap-3 bg-white border border-[#E2E8F0] rounded-lg px-3 py-1.5"
          >
            {/* Rank pill */}
            <span className="text-[10px] font-bold text-[#A0AEC0] w-5 text-center">
              #{rank + 1}
            </span>
            {/* Category color dot */}
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: color }}
              title={d.category}
            />
            {/* Product name */}
            <span className="flex-1 text-sm text-[#1A202C] truncate" title={d.product_name}>
              {d.product_name}
            </span>
            {/* Category label */}
            <span className="text-[10px] text-[#A0AEC0] uppercase tracking-wide hidden sm:inline">
              {d.category.replace(/_/g, ' ')}
            </span>
            {/* Units + euros */}
            <span className="text-sm font-semibold text-[#1A202C] tabular-nums w-12 text-right">
              {d.units}
            </span>
            <span className="text-xs text-[#4A5568] tabular-nums w-14 text-right">
              {_formatEur(d.revenue_eur)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
