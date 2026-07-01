/**
 * Wizard state for the Create Event flow (Phase 4).
 *
 * This is the single in-memory shape the wizard mutates as Omar walks
 * the four steps. It is serialized to localStorage for draft persistence
 * (so closing the tab doesn't lose progress) and finally POSTed to the
 * (yet-to-be-written) finalize endpoint at submit time.
 *
 * NOTHING in this file talks to the backend — the wizard page does that.
 * Keeping types in their own file means the four step components can
 * import the type without circular-importing the page.
 */
import type { ParsedEventPlan, BarSpec } from "@/lib/eventPlan"
import type {
  FullEventDetailEvent,
  FullEventHydrationBag,
} from "@/features/events/useFullEvent"

/** One product on this event. Flat list — no bar column, since
 *  Sundance bars all sell the same menu. Menu rows are generated
 *  at payload time as products × drinks/food bars. */
export interface ProductDraft {
  client_id: string
  name: string
  product_type: "drink" | "food" | "supply" | "ingredient"
  /** Only when product_type='drink'. NULL otherwise. */
  category:
    | "beer_draft" | "beer_bottle"
    | "basic_cocktail" | "premium_cocktail"
    | "wine_red" | "wine_white" | "wine_sparkling"
    | "soft_drink"
    | null
  /** Only when product_type='food'. NULL otherwise. */
  food_type:
    | "burgers" | "sandwiches" | "fried" | "skewers"
    | "pizza" | "gelato" | "other"
    | null
  unit: "bottle" | "glass" | "can" | "draft_glass" | "shot"
      | "piece" | "gram" | "ml"
  /** Default price in EUR cents. What Slesh will show. */
  default_price_cents: number
  /** 0-1 fractional. 0.10 = 10% IVA. NULL = not set. */
  iva_pct: number | null
  /** Deposit charged and refunded. Typically 0 for drinks, non-zero
   *  for glassware/wristbands. NULL = 0. */
  cauzione_cents: number | null
  /** For drinks: override auto-derived tier (1=cheapest, 4=most premium). */
  tier_rank: number | null
  /** Position in the hydrated FullEventDetail.products[] array in
   *  edit mode; undefined for products added client-side. Used by
   *  the payload mapper to remap menu.product_index the same way
   *  BarDraft.hydration_bar_index remaps menu.bar_index. */
  hydration_product_index?: number
}

/** A single bar row in the Step 3 editable table. Mirrors the server-side
 *  BarSpec but adds wizard-only UI fields (slesh_shop_id for the picker). */
export interface BarDraft {
  /** Stable client id so React lists key correctly even before save. */
  client_id: string
  name: string
  device_count: number
  bar_type: "drinks" | "food" | "service" | "recharge"
  /** Filled in Step 6 via the Slesh API picker; null until linked. */
  slesh_shop_id: string | null
  /** Original BarSpec from the Excel parse, if this row came from upload. */
  from_excel: BarSpec | null
  /** Position of this bar in the hydrated FullEventDetail.bars[] array
   *  in edit mode; undefined for bars added client-side. Used by the
   *  payload mapper (Chunk 3b) to remap menu bar_index when the user
   *  reorders or deletes bars. */
  hydration_bar_index?: number
}

export interface WizardState {
  // ── Step 1: Basics
  name: string
  scheduled_at: string                // ISO datetime-local
  scheduled_end_at: string
  venue_id: string | null
  expected_guest_count: number | null
  food_revenue_share_pct: number      // default 30; overrides FoodBarCard default

  // ── Step 2: Excel upload + picked date
  parsed_plan: ParsedEventPlan | null
  picked_date: string | null          // "14/06" once Omar chooses from multi-event list

  // ── Step 3: Products
  products: ProductDraft[]

  // ── Step 4: Bars
  bars: BarDraft[]

  // ── Step 5: Recharge
  // Recharge bars themselves live in `bars` with bar_type='recharge';
  // this step\'s editor just filters that list. The two fields below
  // are denomination preset arrays that don\'t fit the bar model and
  // are stored at the event level.
  recharge_device_count: number             // legacy aggregate; auto-derived from recharge bars
  topup_denominations_user: number[]        // e.g. [10, 20, 50, 100] in euros
  topup_denominations_staff: number[]       // e.g. [5, 10, 20, 50, 100] in euros

  // ── Meta
  current_step: 1 | 2 | 3 | 4 | 5 | 6
  is_dirty: boolean
  /**
   * Set once the event has been created on the server (end of Step 4).
   * Until then, null. Once set, Step 5's invoice uploads attach to this
   * id, the Back button is disabled, and Step 5's "Done" navigates to
   * /events/{event_id}.
   */
  event_id: string | null

  // ── Edit mode hydration bags ──────────────────────────────────────
  // Populated by hydrateWizardState() when the wizard loads an existing
  // event via GET /events/{id}/full; undefined in create mode.
  /** Full backend EventResponse. Carries Slesh-aligned fields the
   *  wizard UI never edits (stripe_ragione_sociale, staff_arrival_time,
   *  wristband_qty_per_type, refund_*, etc.). Chunk 3b's payload mapper
   *  merges these into the PUT so an edit-save does not null them. */
  _loaded_event?: FullEventDetailEvent | null
  /** Products + menu + allocations from the GET. Wizard has no product-
   *  editing UI, so this passes through to the PUT unchanged (bar
   *  indices remapped by the payload mapper). */
  _hydration?: FullEventHydrationBag | null
}

/** Returned by buildEmptyWizardState(). Safe to mount with no prior draft. */
export function buildEmptyWizardState(): WizardState {
  return {
    name: "",
    scheduled_at: "",
    scheduled_end_at: "",
    venue_id: null,
    expected_guest_count: null,
    food_revenue_share_pct: 30,
    parsed_plan: null,
    picked_date: null,
    products: [],
    bars: [],
    recharge_device_count: 0,
    topup_denominations_user: [],
    topup_denominations_staff: [],
    current_step: 1,
    is_dirty: false,
    event_id: null,
  }
}
