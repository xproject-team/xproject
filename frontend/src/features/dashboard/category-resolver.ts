/**
 * Client-side mirror of the backend category resolver.
 *
 * Why: chart-buckets.ts needs a (product_id -> category) map to bucket
 * transactions by category. We DON'T want the dashboard to call a new
 * backend endpoint per render — we already have product data in scope
 * via useAllProducts(). This file derives the category client-side
 * from that data.
 *
 * Taxonomy (locked May 27 2026 with Omar):
 *   Display buckets shown on bar cards (4 drinks + food):
 *     beer | cocktails | premium_cocktails | wine | food
 *   Hidden from cards but still counted toward totals:
 *     other  (covers mixers / supply / spirits / unknown)
 *
 * Resolution strategy (hybrid):
 *   1. If product has a granular category set (Product.category enum from
 *      the backend, e.g. "beer_bottle", "premium_cocktail"), roll up
 *      via _BACKEND_ENUM_TO_BUCKET.
 *   2. Else fall back to substring matching on the product NAME via
 *      _NAME_KEYWORDS (mirror of backend _classify_category()).
 *      Order matters: premium_cocktails MUST be checked BEFORE cocktails
 *      because "Cocktail Super premium" contains the substring "cocktail".
 *
 * This file imports NO React, NO network, NO heavy deps. Pure functions,
 * cheaply tested.
 */

export type DisplayBucket =
  | 'beer'
  | 'cocktails'
  | 'premium_cocktails'
  | 'wine'
  | 'food'
  | 'other'

// ─── Granular backend enum -> display bucket ────────────────────────────
// Mirrors backend ProductCategory enum (app/modules/products/models.py).
// Values not in this map fall through to 'other'.
const _BACKEND_ENUM_TO_BUCKET: Record<string, DisplayBucket> = {
  beer_bottle:      'beer',
  beer_draft:       'beer',
  basic_cocktail:   'cocktails',
  premium_cocktail: 'premium_cocktails',
  wine_red:         'wine',
  wine_white:       'wine',
  wine_sparkling:   'wine',
  soft_drink:       'other',   // mixers / non-alcoholic, hidden from cards
}

// ─── Name keywords (substring match) -> display bucket ─────────────────
// Mirrors backend _classify_category() in
// app/modules/predictions/predictors/heuristic.py.
// Order matters: first matching bucket wins. premium_cocktails BEFORE
// cocktails because "Cocktail Super premium" / "Cocktail signature"
// contain the substring "cocktail" and would otherwise be swallowed.
const _NAME_KEYWORDS: [DisplayBucket, readonly string[]][] = [
  ['beer',              ['beer', 'lager', 'ale', 'pilsner', 'stout',
                          'birra', 'raffo', 'nastro azzurro', 'nastro']],
  ['wine',              ['wine', 'vino', 'prosecco', 'champagne', 'spumante',
                          'bottiglia vino', 'vino e bolle', 'bolle']],
  // SPECIFIC premium phrases only — never the bare word "cocktail".
  ['premium_cocktails', ['super premium', 'signature', 'premium cocktail',
                          'cocktail super', 'cocktail signature']],
  ['cocktails',         ['cocktail', 'mojito', 'spritz', 'sprtiz',
                          'negroni', 'martini', 'margarita', 'aperol']],
  ['food',              ['burger', 'mortadella', 'porchetta', 'prosciutto', 'veg',
                          'patatina', 'patatine', 'focaccia', 'panino', 'panini',
                          'tramezzino', 'piadina', 'arrosticini', 'arancin']],
  // 'other' is the implicit fallback below.
]

/** Public input shape — anything with these two fields works. */
export interface ProductLike {
  id:       string
  name:     string
  // Optional because mock-shape Products may lack it; real backend Product
  // always has it (sometimes null for food/ingredients/supplies).
  category?: string | null
}

/**
 * Resolve one product to a display bucket.
 *
 * Hybrid: granular Product.category first, name fallback otherwise.
 * Always returns a bucket (never null). Unknown -> 'other'.
 */
export function resolveCategory(p: ProductLike): DisplayBucket {
  if (p.category) {
    const fromEnum = _BACKEND_ENUM_TO_BUCKET[p.category]
    if (fromEnum) return fromEnum
    // Fall through if the enum value isn't in our display map
    // (e.g. soft_drink -> already mapped to 'other' above)
  }
  const name = p.name.toLowerCase()
  for (const [bucket, keywords] of _NAME_KEYWORDS) {
    if (keywords.some((k) => name.includes(k))) {
      return bucket
    }
  }
  return 'other'
}

/**
 * Build the (product_id -> bucket) map that buildMultiLineBarRevenuePoints
 * expects in chart-buckets.ts.
 *
 * Caller passes in the products array (usually from useAllProducts()),
 * gets back a flat lookup map. O(N) one-time per render.
 */
export function buildCategoryByProductId(
  products: ProductLike[],
): Record<string, DisplayBucket> {
  const map: Record<string, DisplayBucket> = {}
  for (const p of products) {
    map[p.id] = resolveCategory(p)
  }
  return map
}
