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
 *   - products come from state.products[] (Step 3's editable list,
 *     itself seeded from parsed_plan.products[] on Excel upload — see
 *     WizardStep2Upload.tsx). If Omar never uploads and never adds a
 *     product by hand, products = [] and menu = [] are sent. Backend
 *     handles empty lists fine.
 *
 *   - menu (event_products / listini lines) is a CROSS PRODUCT: every
 *     product × every bar with bar_type in {drinks, food}. At Sundance
 *     every drinks/food bar sells the same menu, so there is no per-row
 *     "which bar" column in the UI — Omar edits one flat product list
 *     and every drinks/food bar gets every product. Recharge/service
 *     bars get no menu rows.
 *
 *   - allocations (bar_stock starting qty) has no wizard UI. Create
 *     mode always sends []; edit mode passes through the hydrated
 *     allocations, remapped to current bar/product positions (see
 *     applyEditModeMerges below). Starting stock is otherwise set via
 *     /inventory/allocate on event day.
 *
 *   - Pre-validation produces human-readable error strings. They\'re
 *     surfaced before the API call so Omar sees \'venue is required\'
 *     instead of a 422 explaining the same thing.
 */
import type { WizardState } from "./types"
import type {
  FullEventCreatePayload,
  FullEventBarInput,
  FullEventProductInput,
  FullEventMenuItemInput,
  FullEventAllocationInput,
} from "@/features/events/useCreateFullEvent"

export interface BuildResult {
  payload: FullEventCreatePayload | null
  preErrors: string[]
}

/**
 * Edit-mode post-processing. In create mode this is a no-op.
 *
 * WizardState carries only ~8 of ~15 event basics and no UI for
 * allocations (starting bar_stock). Without this merge, a PUT would
 * null out the Slesh basics (stripe_ragione_sociale,
 * wristband_qty_per_type, refund_*, staff_arrival_time) and wipe the
 * starting allocations, because the create-mode mapper emits
 * allocations=[] unconditionally.
 *
 * Products + menu need no special edit-mode handling any more:
 * state.products is the source of truth in both create and edit mode
 * (hydrateWizardState populates it from GET .../full), so
 * buildFullEventPayload's cross-product mapper already produced the
 * right thing.
 *
 * Allocations remap: allocation rows in the hydration bag reference
 * bars/products by their position in the ORIGINAL hydrated bars[]/
 * products[] arrays (`hydration_bar_index` / `hydration_product_index`).
 * If Omar reordered or deleted bars/products, we remap those indices
 * to the CURRENT positions and drop rows whose bar or product was
 * deleted (or, if Omar re-uploaded an Excel plan, whose bar/product
 * has no hydration index at all).
 */
function applyEditModeMerges(
  payload: FullEventCreatePayload,
  state: WizardState,
): FullEventCreatePayload {
  const loaded = state._loaded_event
  if (!loaded) return payload   // create mode — no-op

  // ── Slesh basics passthrough (WizardState has no UI for these) ──
  const event = {
    ...payload.event,
    stripe_ragione_sociale:   loaded.stripe_ragione_sociale,
    staff_arrival_time:       loaded.staff_arrival_time,
    wristband_qty_per_type:   loaded.wristband_qty_per_type,
    refund_min_credit_cents:  loaded.refund_min_credit_cents,
    refund_fee_cents:         loaded.refund_fee_cents,
    refund_window_open_at:    loaded.refund_window_open_at,
    refund_window_close_at:   loaded.refund_window_close_at,
    // Wizard's Step 5 edits user denominations only; staff denominations
    // have no UI. If wizard user denominations are empty we assume the
    // user did not touch them and preserve the loaded value.
    topup_denominations_user:
      state.topup_denominations_user.length > 0
        ? state.topup_denominations_user
        : loaded.topup_denominations_user,
    topup_denominations_staff:
      state.topup_denominations_staff.length > 0
        ? state.topup_denominations_staff
        : loaded.topup_denominations_staff,
  }

  // ── Allocations (bar_stock) — the only bag still not editable ──
  let allocations = payload.allocations

  if (state._hydration) {
    const hydration = state._hydration

    // hydration_bar_index (original position) → current position.
    // Bars added client-side (or brought in by a re-upload) have
    // hydration_bar_index === undefined and are not in the map;
    // allocation rows pointing at them have no entry and are dropped.
    const barRemap = new Map<number, number>()
    state.bars.forEach((bar, currentIndex) => {
      if (bar.hydration_bar_index !== undefined) {
        barRemap.set(bar.hydration_bar_index, currentIndex)
      }
    })

    // Same idea for products: hydration_product_index (original
    // position in GET .../full's products[]) → current position in
    // the products[] we just emitted. Must apply the SAME empty-name
    // filter buildFullEventPayload used, so positions line up.
    const nonEmptyProducts = state.products.filter((p) => p.name.trim() !== "")
    const productRemap = new Map<number, number>()
    nonEmptyProducts.forEach((p, currentIndex) => {
      if (p.hydration_product_index !== undefined) {
        productRemap.set(p.hydration_product_index, currentIndex)
      }
    })

    allocations = hydration.allocations
      .map((a): FullEventAllocationInput | null => {
        const newBarIndex = barRemap.get(a.bar_index)
        const newProductIndex = productRemap.get(a.product_index)
        return newBarIndex === undefined || newProductIndex === undefined
          ? null
          : { ...a, bar_index: newBarIndex, product_index: newProductIndex }
      })
      .filter((a): a is FullEventAllocationInput => a !== null)
  }

  return { event, bars: payload.bars, products: payload.products, menu: payload.menu, allocations }
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

  // ── Step 4 Bars validation ──────────────────────────────────────
  // (Runs before Step 3 Products validation below, since the latter
  // needs to know which bar_types are present.)
  if (state.bars.length === 0) {
    preErrors.push("Bars: add at least one bar")
  }
  state.bars.forEach((b, i) => {
    if (b.name.trim() === "") preErrors.push(`Bars: row ${i + 1} needs a name`)
    // slesh_shop_id is not strictly required — Omar can link later;
    // the wizard already shows an amber hint for unlinked bars.
  })

  // ── Step 3 Products validation ───────────────────────────────────
  // Not a hard requirement on its own — an event with only recharge/
  // service bars legitimately has no products. It only becomes an
  // error once there\'s a drinks/food bar with nothing to sell.
  const hasMenuBar = state.bars.some((b) => b.bar_type === "drinks" || b.bar_type === "food")
  if (state.products.length === 0 && hasMenuBar) {
    preErrors.push("Products: add at least one product")
  }

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

  // ── Products → FullEventProductInput[] ──────────────────────────
  // Skip rows with an empty name — the UI\'s soft-delete (Omar clears
  // the name field instead of removing the card mid-edit).
  const products: FullEventProductInput[] = state.products
    .filter((p) => p.name.trim() !== "")
    .map((p) => ({
      name:                p.name.trim(),
      product_type:        p.product_type,
      category:            p.category,       // backend enforces null when non-drink
      food_type:           p.food_type,
      unit:                p.unit,
      default_price_cents: p.default_price_cents,
      iva_pct:             p.iva_pct,
      cauzione_cents:      p.cauzione_cents,
      tier_rank:           p.tier_rank,       // backend derives when null
    }))

  // ── Menu → cross product of products × drinks-or-food bars ─────
  // Sundance\'s actual model: every drinks/food bar sells the same
  // menu, so there\'s no per-row "which bar" in the Products step.
  // Recharge/service bars get no menu rows.
  const menu: FullEventMenuItemInput[] = []
  bars.forEach((bar, barIndex) => {
    if (bar.bar_type !== "drinks" && bar.bar_type !== "food") return
    products.forEach((product, productIndex) => {
      menu.push({
        bar_index:     barIndex,
        product_index: productIndex,
        price_cents:   product.default_price_cents ?? 0,
        is_available:  true,
      })
    })
  })

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

  return { payload: applyEditModeMerges(payload, state), preErrors: [] }
}
