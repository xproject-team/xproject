/**
 * buildFullEventPayload — map WizardState → FullEventCreatePayload.
 *
 * This is the single source of truth for how the wizard turns its
 * in-memory state into the atomic POST /events/full request. Keeping
 * it in its own file (vs. embedded in the page) means it\'s testable
 * standalone and easy to evolve as the wizard adds steps.
 *
 * The backend endpoint and types it expects are documented in:
 *   - features/events/useCreateFullEvent.ts (TS types + the hook)
 *   - backend app/modules/events/schemas.py (Pydantic schemas)
 *
 * Mapping notes:
 *
 *   - bars.slesh_shop_id (FE/wizard term) → slesh_negozio_id (BE term).
 *     Italian for \'shop_id\'; the column on the bars table predates the
 *     wizard. Mapped explicitly so future field-rename refactors only
 *     touch this file.
 *
 *   - products come from parsed_plan.products[] (the Excel listini).
 *     If the user skipped upload, products = [] and menu = [] are sent.
 *     Backend handles empty lists fine.
 *
 *   - menu (event_products / listini lines) maps each parsed product
 *     to its bar by name. The lookup uses BOTH the bar\'s current name
 *     AND its from_excel.name to handle the case where Omar edited a
 *     bar\'s name in Step 3 after the upload pre-filled it.
 *
 *   - allocations (bar_stock starting qty) is always [] from the
 *     wizard — that\'s handled by /inventory/allocate on event day.
 *
 *   - Pre-validation produces human-readable error strings. They\'re
 *     surfaced before the API call so Omar sees \'venue is required\'
 *     instead of a 422 explaining the same thing.
 */
import type { WizardState, BarDraft } from "./types"
import type {
  FullEventCreatePayload,
  FullEventBarInput,
  FullEventProductInput,
  FullEventMenuItemInput,
} from "@/features/events/useCreateFullEvent"

/** Map an Excel ProductSpec category string onto the backend\'s
 *  product_type enum. The Excel\'s category column is a free-text-ish
 *  label (e.g. "Cocktail", "Birra", "Acqua") which the backend stores
 *  as a category enum but ALSO needs a product_type. Drinks get
 *  product_type=\'drink\'; food gets \'food\'; everything else falls
 *  back to \'supply\' (catch-all for non-revenue items). */
// Backend's ProductCategory enum — keep in sync with
// app/modules/products/models.py ProductCategory. We map the Excel\'s
// free-text category strings onto this when possible; otherwise we
// store null and let Omar categorize via the Catalog page later.
// Strict allow-list: anything not in here is dropped to null.
const VALID_PRODUCT_CATEGORIES = new Set([
  "beer_draft", "beer_bottle",
  "basic_cocktail", "premium_cocktail",
  "wine_red", "wine_white", "wine_sparkling",
  "soft_drink",
])

function normalizeCategory(raw: string | null | undefined): string | null {
  if (!raw) return null
  const norm = raw.trim().toLowerCase().replace(/[\s-]+/g, "_")
  if (VALID_PRODUCT_CATEGORIES.has(norm)) return norm
  // Cheap heuristics — map common Excel labels to the closest enum
  if (norm.includes("beer") || norm.includes("birra")) {
    return norm.includes("draft") || norm.includes("spina") ? "beer_draft" : "beer_bottle"
  }
  if (norm.includes("wine") || norm.includes("vino")) {
    if (norm.includes("red") || norm.includes("rosso")) return "wine_red"
    if (norm.includes("white") || norm.includes("bianco")) return "wine_white"
    if (norm.includes("spark") || norm.includes("bollic")) return "wine_sparkling"
    return "wine_red"
  }
  if (norm.includes("cocktail")) {
    return norm.includes("premium") || norm.includes("signature") ? "premium_cocktail" : "basic_cocktail"
  }
  if (norm.includes("soft") || norm.includes("soda") || norm.includes("water") || norm.includes("acqua")) {
    return "soft_drink"
  }
  return null
}

function deriveProductType(
  category: string | null | undefined,
  barType: BarDraft["bar_type"] | null,
): "drink" | "food" | "ingredient" | "supply" {
  if (barType === "food") return "food"
  if (barType === "drinks") return "drink"
  if (barType === "service" || barType === "recharge") return "supply"
  // Fall back to category heuristic for products without a clear bar match
  const c = (category ?? "").toLowerCase()
  if (c.includes("food") || c.includes("cibo") || c.includes("pizza")) return "food"
  return "drink"
}


/** Look up a bar in state.bars by ProductSpec.bar_name.
 *  Returns its index, or -1 if not found.
 *
 *  Match strategy is generous: case-insensitive, trim, AND
 *  compares against both the bar\'s current name and its
 *  from_excel.name (the original Excel name, preserved as the
 *  stable identifier when Omar edits the display name). */
function findBarIndexByName(bars: BarDraft[], barName: string): number {
  const target = barName.trim().toLowerCase()
  if (target === "") return -1
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i]
    if (b.name.trim().toLowerCase() === target) return i
    if (b.from_excel && b.from_excel.name.trim().toLowerCase() === target) return i
  }
  return -1
}

export interface BuildResult {
  payload: FullEventCreatePayload | null
  preErrors: string[]
}

export function buildFullEventPayload(state: WizardState): BuildResult {
  const preErrors: string[] = []

  // ── Step 1 Basics validation ────────────────────────────────────
  if (state.name.trim() === "") preErrors.push("Basics: event name is required")
  if (state.venue_id === null || state.venue_id === "") preErrors.push("Basics: venue is required")
  if (state.scheduled_at === "") preErrors.push("Basics: start datetime is required")
  if (state.scheduled_end_at === "") preErrors.push("Basics: end datetime is required")
  if (state.scheduled_at !== "" && state.scheduled_end_at !== "" &&
      new Date(state.scheduled_end_at) <= new Date(state.scheduled_at)) {
    preErrors.push("Basics: end must be after start")
  }
  if (state.food_revenue_share_pct < 0 || state.food_revenue_share_pct > 100) {
    preErrors.push("Basics: food share must be 0–100")
  }

  // ── Step 3 Bars validation ──────────────────────────────────────
  if (state.bars.length === 0) {
    preErrors.push("Bars: add at least one bar")
  }
  state.bars.forEach((b, i) => {
    if (b.name.trim() === "") preErrors.push(`Bars: row ${i + 1} needs a name`)
    // slesh_shop_id is not strictly required — Omar can link later;
    // the wizard already shows an amber hint for unlinked bars.
  })

  // Early exit if event-level validation fails — no point mapping the rest.
  if (preErrors.length > 0) return { payload: null, preErrors }

  // ── Bars → FullEventBarInput[] ──────────────────────────────────
  const bars: FullEventBarInput[] = state.bars.map((b) => ({
    name:             b.name.trim(),
    slesh_negozio_id: b.slesh_shop_id,   // FE→BE field name remap
    bar_type:         b.bar_type,
    device_count:     b.device_count,
    slesh_category:   null,
    is_active:        true,
  }))

  // ── Products + menu (only if Excel was parsed) ──────────────────
  // Products dedup by (name, product_type) since the backend reuses
  // existing tenant-global products by that key. Menu lines reference
  // products by INDEX into the array we\'re building here.
  const products: FullEventProductInput[] = []
  const productIndexByKey = new Map<string, number>()
  const menu: FullEventMenuItemInput[] = []
  const menuPairs = new Set<string>()           // dedup (bar_index, product_index)

  if (state.parsed_plan && state.parsed_plan.products.length > 0) {
    for (const spec of state.parsed_plan.products) {
      // STEP 10 LEARNING: the Slesh Excel uses DIFFERENT bar names in
      // the Device Count sheet ("MAIN BAR", "STAGE BAR") vs the Listini
      // sheets ("Cocktail Bar", "Beer Bar"). The findBarIndexByName
      // lookup misses most products. Rather than silently dropping them
      // (which leaves Catalog empty after finalize), we create the
      // product UNCONDITIONALLY and only emit a menu line when the bar
      // lookup succeeds. Result: all products land in Catalog; price-
      // by-bar listini lines get added later via Edit Event when Omar
      // maps "Cocktail Bar -> MAIN BAR".
      const bIndex = findBarIndexByName(state.bars, spec.bar_name)
      const barTypeForType = bIndex >= 0 ? state.bars[bIndex].bar_type : null
      // Pre-compute the category before deriving product_type so we
      // can downgrade drink->supply when the category is unrecognized
      // (backend\'s _validate_shape rejects category=null on drinks).
      // Effect: products land in Catalog as supplies; Omar promotes
      // them back to drinks once he sets a category via the Catalog UI.
      const initialType = deriveProductType(spec.category, barTypeForType)
      const normalizedCategory = initialType === "drink"
        ? normalizeCategory(spec.category)
        : null
      const productType: "drink" | "food" | "ingredient" | "supply" =
        initialType === "drink" && normalizedCategory === null
          ? "supply"
          : initialType
      const key = `${spec.name.trim().toLowerCase()}|${productType}`

      let pIndex = productIndexByKey.get(key)
      if (pIndex === undefined) {
        pIndex = products.length
        productIndexByKey.set(key, pIndex)
        // Build the product input inline so we can pass the explicit
        // overriden product_type + already-normalized category.
        products.push({
          name:                spec.name.trim(),
          product_type:        productType,
          category:            productType === "drink" ? normalizedCategory : null,
          food_type:           null,
          unit:                "bottle",
          default_price_cents: spec.price_cents ?? null,
          iva_pct:             spec.iva_pct == null ? null : spec.iva_pct / 100,
          cauzione_cents:      spec.cauzione_cents ?? null,
        })
      }

      // Only add a menu line when we can resolve the bar. Products
      // without a bar match still land in Catalog; they\'re just not
      // pre-priced at any bar.
      if (bIndex < 0) continue
      const pairKey = `${bIndex}|${pIndex}`
      if (menuPairs.has(pairKey)) continue        // dedup: same product at same bar
      menuPairs.add(pairKey)
      menu.push({
        bar_index:     bIndex,
        product_index: pIndex,
        price_cents:   spec.price_cents,
        is_available:  true,
      })
    }
  }

  // ── Event ────────────────────────────────────────────────────────
  const payload: FullEventCreatePayload = {
    event: {
      name:                       state.name.trim(),
      venue_id:                   state.venue_id ?? "",
      scheduled_at:               state.scheduled_at,
      scheduled_end_at:           state.scheduled_end_at,
      expected_guest_count:       state.expected_guest_count,
      food_revenue_share_pct:     state.food_revenue_share_pct,
      topup_denominations_user:   state.topup_denominations_user.length > 0 ? state.topup_denominations_user  : null,
      topup_denominations_staff:  state.topup_denominations_staff.length > 0 ? state.topup_denominations_staff : null,
    },
    bars,
    products,
    menu,
    allocations: [],           // /inventory/allocate handles starting stock
  }

  return { payload, preErrors: [] }
}
