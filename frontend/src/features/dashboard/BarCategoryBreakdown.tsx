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
  // Drinks
  beer:              '#C49A2A',
  cocktails:         '#C2185B',
  premium_cocktails: '#6A1B9A',
  wine:              '#8B0000',
  soft_drink:        '#0288D1',
  // Food sub-buckets (FoodType enum values)
  burgers:           '#D84315',
  sandwiches:        '#F9A825',
  fried:             '#FB8C00',
  skewers:           '#6D4C41',
  pizza:             '#C62828',
  gelato:            '#7E57C2',
  other:             '#558B2F',
  // Deprecated single-bucket fallback (only when food_type IS NULL)
  food:              '#558B2F',
}

const _BUCKET_LABEL: Record<BarCategoryBucketDTO['bucket'], string> = {
  beer:              'Beer',
  cocktails:         'Cocktails',
  premium_cocktails: 'Premium',
  wine:              'Wine',
  soft_drink:        'Soft Drinks',
  burgers:           'Burgers',
  sandwiches:        'Sandwiches',
  fried:             'Fried',
  skewers:           'Skewers',
  pizza:             'Pizza',
  gelato:            'Gelato',
  other:             'Other',
  food:              'Food',
}

// Granular category -> bucket key used for the color dot on top-5 rows.
// Drinks roll up; food types map to themselves (already bucket keys).
const _GRANULAR_TO_BUCKET: Record<string, BarCategoryBucketDTO['bucket']> = {
  // Drink categories
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
  soft_drink:       'soft_drink',
  // Food types (identity mapping — already bucket keys)
  burgers:          'burgers',
  sandwiches:       'sandwiches',
  fried:            'fried',
  skewers:          'skewers',
  pizza:            'pizza',
  gelato:           'gelato',
  other:            'other',
  food:             'food',
}

function _bucketFor(granular: string): BarCategoryBucketDTO['bucket'] {
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
  /** Bar type — drives which buckets render. Food bars render nothing here;
   *  the overlay renders a food-items list instead. */
  bar_type?: 'drinks' | 'food' | 'mixed' | 'merch' | 'service'
}

// Drink bucket preference order for stable left-to-right rendering.
const _DRINK_ORDER: BarCategoryBucketDTO['bucket'][] = [
  'beer', 'cocktails', 'premium_cocktails', 'wine', 'soft_drink',
]
// Food bucket preference order (FoodType enum order).
const _FOOD_ORDER: BarCategoryBucketDTO['bucket'][] = [
  'burgers', 'sandwiches', 'fried', 'skewers', 'pizza', 'gelato', 'other', 'food',
]

export function BarCategoryBreakdown({ bar, bar_type }: BarCategoryBreakdownProps) {
  if (!bar || bar.categories.length === 0) {
    return (
      <p className="text-sm text-[#A0AEC0] italic">
        No sales yet by category.
      </p>
    )
  }

  // Render only buckets that actually exist on this event's menu (i.e. that
  // produced sales). Empty placeholder pills are dropped per Hesam's spec:
  // "squares must be in sync with the event menu".
  const reference = bar_type === 'food' ? _FOOD_ORDER : _DRINK_ORDER
  const byBucket = new Map(bar.categories.map((c) => [c.bucket, c]))
  // Stable order: reference first (in known order), then any extras the
  // backend may add later (forward-compatible).
  const ordered: BarCategoryBucketDTO['bucket'][] = []
  for (const b of reference) if (byBucket.has(b)) ordered.push(b)
  for (const c of bar.categories) if (!ordered.includes(c.bucket)) ordered.push(c.bucket)

  // Responsive grid: scales with bucket count. Food trucks may have 1-3,
  // drink bars typically 4-5. Cap at 5 cols on small screens.
  const cols = Math.min(ordered.length, 5)
  const gridClass = [
    'grid gap-2',
    cols <= 2 ? 'grid-cols-2' :
    cols === 3 ? 'grid-cols-2 sm:grid-cols-3' :
    cols === 4 ? 'grid-cols-2 sm:grid-cols-4' :
                 'grid-cols-2 sm:grid-cols-5',
  ].join(' ')

  return (
    <div className={gridClass}>
      {ordered.map((b) => {
        const row = byBucket.get(b)
        if (!row) return null
        const units = row.units
        const rev = row.revenue_eur
        return (
          <div
            key={b}
            className="border rounded-lg px-3 py-2 text-center bg-white border-[#E2E8F0]"
          >
            <p
              className="text-[10px] uppercase tracking-wide font-semibold"
              style={{ color: _BUCKET_COLOR[b] ?? '#4A5568' }}
            >
              {_BUCKET_LABEL[b] ?? b.replace(/_/g, ' ')}
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
  /** Bar type — food bars render food items elsewhere, so this returns null. */
  bar_type?: 'drinks' | 'food' | 'mixed' | 'merch' | 'service'
}

export function BarTopDrinks({ bar, bar_type: _bar_type }: BarTopDrinksProps) {
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
        const color = _BUCKET_COLOR[bucket] ?? '#A0AEC0'
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
