/**
 * Mirrors the backend's ParsedEventPlan dataclass family.
 * Source of truth: app/modules/events/event_plan_excel/schemas.py
 *
 * Keep these in sync. If the backend adds a field, add it here too.
 */
export interface ContactSpec {
  role: string
  name: string | null
  email: string | null
  phone: string | null
}

export interface BarSpec {
  name: string
  device_count: number
  bar_type: "drinks" | "food" | "service" | "recharge"
  notes: string | null
}

export interface ProductSpec {
  name: string
  bar_name: string
  category: string
  price_cents: number
  iva_pct: number
  cauzione_cents: number
}

export interface ParseWarning {
  sheet: string
  where: string
  message: string
}

export interface ParsedEventPlan {
  event_name: string | null
  event_dates: string[]                  // ["14/06", "05/07", ...]
  event_start_time: string | null
  event_end_time: string | null
  staff_arrival_time: string | null
  venue_name: string | null
  venue_address: string | null
  capacity: number | null
  expected_guests: number | null
  contacts: ContactSpec[]
  topup_denominations_user: number[]
  topup_denominations_staff: number[]
  refund_min_credit_cents: number | null
  refund_fee_cents: number | null
  drink_bars: BarSpec[]
  food_bars: BarSpec[]
  other_bars: BarSpec[]
  recharge_device_count: number
  products: ProductSpec[]
  warnings: ParseWarning[]
}
