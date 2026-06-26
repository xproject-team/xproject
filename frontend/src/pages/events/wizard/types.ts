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

  // ── Step 3: Bars
  bars: BarDraft[]

  // ── Step 4: Recharge
  recharge_device_count: number

  // ── Meta
  current_step: 1 | 2 | 3 | 4
  is_dirty: boolean
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
    bars: [],
    recharge_device_count: 0,
    current_step: 1,
    is_dirty: false,
  }
}
