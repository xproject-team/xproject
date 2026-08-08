/**
 * Wizard Step 1 — Basics
 *
 * Event name, dates, venue, expected guests, owner's food revenue share.
 * Pre-fills from parsed_plan (Step 2 upload) when available, but every
 * field stays editable. Validates inline; the wizard footer's "Save &
 * Continue" still navigates either way, but red field-level messages
 * surface what's missing so Omar can fix it before Finalize.
 *
 * Why this is Step 1 even though it depends on Step 2's parse:
 *   The wizard’s natural order has Basics first (it’s the
 *   identity of the event). When Omar uploads in Step 2 first,
 *   Step 1 ends up pre-populated and he just confirms. If he’s
 *   doing manual config (skipped upload), Step 1 is where he types
 *   the values.
 *
 * Date wiring quirk worth knowing:
 *   parsed_plan.picked_date is "DD/MM" (e.g. "05/07"). We combine it
 *   with the current year + Excel start/end times. If the resulting
 *   datetime would land in the past, we bump to next year. Omar can
 *   see the final value in the input and override it if our guess is
 *   wrong, so the worst case is one keystroke of correction.
 *
 * Venue handling:
 *   parsed_plan.venue_name is a free-text string from Slesh
 *   ("Villa Alberico"). We try to match it case-insensitively against
 *   the existing venues list (loaded via useVenues). If found, the
 *   dropdown auto-selects. If not found, Omar picks from the dropdown
 *   or leaves it blank — Phase 4.X will add "+ Create new venue" once
 *   the venues API exposes a create endpoint we can hit from here.
 *   Until then, an unmatched Slesh venue name just means a manual pick.
 */
import { useEffect, useMemo } from "react"

import { useVenues } from "@/features/venues/hooks"
import type { WizardState } from "../types"
import { inputCls, dateInputCls, Label, HelperText, stepCardCls, warningBannerCls, warningBannerStyle } from "@/design-system/wizardForm"
import "@/design-system/components/components.css"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

// ── Date helpers ───────────────────────────────────────────────────
// datetime-local <-> UTC ISO. datetime-local is naive LOCAL time;
// we store UTC. Identical helpers to EventCreatePage.
const toUtcIso = (local: string): string => (local ? new Date(local).toISOString() : "")
const toLocalInput = (iso: string): string => {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * Combine a DD/MM string from the Excel + a HH:MM time + current year
 * into a datetime-local string suitable for <input type="datetime-local">.
 * If the resulting moment is in the past, we bump to next year — Omar
 * uploaded a plan for an upcoming event, not a historical one.
 *
 * Returns "" if either input is malformed (callers see an empty field
 * and can type it themselves).
 */
function combineDateTime(ddmm: string, hhmm: string | null): string {
  if (!ddmm || !/^\d{1,2}\/\d{1,2}$/.test(ddmm)) return ""
  if (!hhmm || !/^\d{1,2}:\d{2}$/.test(hhmm)) return ""
  const [dayStr, monthStr] = ddmm.split("/")
  const [hourStr, minStr] = hhmm.split(":")
  const day = parseInt(dayStr, 10)
  const month = parseInt(monthStr, 10) - 1  // 0-indexed for Date
  const hour = parseInt(hourStr, 10)
  const minute = parseInt(minStr, 10)
  const year = new Date().getFullYear()
  let dt = new Date(year, month, day, hour, minute)
  if (dt.getTime() < Date.now()) {
    dt = new Date(year + 1, month, day, hour, minute)
  }
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`
}

export function WizardStep1Basics({ state, onChange }: Props) {
  const { data: venues = [] } = useVenues()

  // ── Auto-fill from parsed plan ───────────────────────────────────
  // Runs ONCE per parsed_plan + picked_date pair. We only fill fields
  // the user hasn’t already touched. This is the single place
  // where Excel data flows into Step 1 — keeping it in one effect
  // makes the logic auditable.
  useEffect(() => {
    if (!state.parsed_plan) return
    const plan = state.parsed_plan
    const patch: Partial<WizardState> = {}

    if (!state.name && plan.event_name) {
      patch.name = plan.event_name
    }
    if (!state.expected_guest_count && plan.expected_guests != null) {
      patch.expected_guest_count = plan.expected_guests
    }
    // Date wiring — only attempts when picked_date is set
    if (state.picked_date) {
      if (!state.scheduled_at) {
        const iso = toUtcIso(combineDateTime(state.picked_date, plan.event_start_time))
        if (iso) patch.scheduled_at = iso
      }
      if (!state.scheduled_end_at) {
        const iso = toUtcIso(combineDateTime(state.picked_date, plan.event_end_time))
        if (iso) patch.scheduled_end_at = iso
      }
    }
    // Venue match — case-insensitive name match against existing list
    if (!state.venue_id && plan.venue_name && venues.length > 0) {
      const target = plan.venue_name.trim().toLowerCase()
      const match = venues.find(
        (v: { id: string; name: string }) => v.name.trim().toLowerCase() === target
      )
      if (match) patch.venue_id = match.id
    }

    if (Object.keys(patch).length > 0) {
      onChange(patch)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.parsed_plan, state.picked_date, venues.length])

  // ── Validation hints (informational; the footer button still works) ─
  const errors = useMemo(() => {
    const out: string[] = []
    if (!state.name.trim()) out.push("Event name is required.")
    if (!state.scheduled_at) out.push("Start datetime is required.")
    if (!state.scheduled_end_at) out.push("End datetime is required.")
    if (state.scheduled_at && state.scheduled_end_at) {
      if (new Date(state.scheduled_end_at).getTime() <= new Date(state.scheduled_at).getTime()) {
        out.push("End must be after Start.")
      }
    }
    if (!state.venue_id) out.push("Venue is required.")
    return out
  }, [state.name, state.scheduled_at, state.scheduled_end_at, state.venue_id])

  // ── Field handlers ────────────────────────────────────────────────
  const setName = (v: string) => onChange({ name: v })
  const setVenueId = (v: string) => onChange({ venue_id: v || null })
  const setStartLocal = (local: string) => onChange({ scheduled_at: toUtcIso(local) })
  const setEndLocal = (local: string) => onChange({ scheduled_end_at: toUtcIso(local) })
  const setGuests = (v: string) =>
    onChange({ expected_guest_count: v === "" ? null : Math.max(0, Math.floor(Number(v) || 0)) })
  const setFoodShare = (v: string) => {
    if (v === "") {
      onChange({ food_revenue_share_pct: 30 })  // default
      return
    }
    const n = Math.max(0, Math.min(100, Math.round(Number(v) || 0)))
    onChange({ food_revenue_share_pct: n })
  }

  // Pre-existing data hint
  const fromExcel = state.parsed_plan !== null

  return (
    <div className={stepCardCls}>
      {fromExcel && (
        <div
          className="relative overflow-hidden mb-4 px-4 py-3 rounded-[var(--v-radius)] flex items-start gap-2"
          style={{ background: "var(--v-surface-raised)", border: "0.5px solid var(--v-border)" }}
        >
          <span className="absolute left-0 top-0 bottom-0 w-[2px]" style={{ background: "var(--v-cyan)" }} />
          <svg className="w-4 h-4 mt-0.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="var(--v-cyan)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />
          </svg>
          <span className="text-[13px]" style={{ color: "var(--v-text-muted)" }}>
            Some fields below have been pre-filled from the uploaded plan. You can edit anything.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="sm:col-span-2">
          <Label>Event Name</Label>
          <input
            className={inputCls}
            value={state.name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sundance Sunday"
          />
        </div>

        <div>
          <Label>Venue</Label>
          <select
            className={inputCls}
            value={state.venue_id ?? ""}
            onChange={(e) => setVenueId(e.target.value)}
          >
            <option value="">Select venue…</option>
            {venues.map((v: { id: string; name: string }) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
          {state.parsed_plan?.venue_name && !state.venue_id && (
            <HelperText>
              Plan says "{state.parsed_plan.venue_name}" — not found in your venues list. Pick one above.
            </HelperText>
          )}
        </div>

        <div>
          <Label>Expected Guests</Label>
          <input
            type="number"
            min={0}
            className={inputCls}
            value={state.expected_guest_count == null ? "" : String(state.expected_guest_count)}
            onChange={(e) => setGuests(e.target.value)}
            placeholder="e.g. 1600"
          />
        </div>

        <div>
          <Label>Start</Label>
          <input
            type="datetime-local"
            className={dateInputCls}
            value={toLocalInput(state.scheduled_at)}
            onChange={(e) => setStartLocal(e.target.value)}
          />
        </div>

        <div>
          <Label>End</Label>
          <input
            type="datetime-local"
            className={dateInputCls}
            value={toLocalInput(state.scheduled_end_at)}
            onChange={(e) => setEndLocal(e.target.value)}
          />
        </div>

        <div className="sm:col-span-2">
          <Label>Food revenue share — owner's % (default 30)</Label>
          <input
            type="number"
            min={0}
            max={100}
            className={inputCls}
            value={String(state.food_revenue_share_pct)}
            onChange={(e) => setFoodShare(e.target.value)}
            placeholder="e.g. 30"
          />
          <HelperText>
            What percent of food-vendor gross revenue Omar keeps. Drives the FoodBarCard's "Omar's Cut" tile.
          </HelperText>
        </div>
      </div>

      {errors.length > 0 && (
        <div className={`mt-5 ${warningBannerCls}`} style={warningBannerStyle}>
          <p className="text-xs font-semibold mb-1" style={{ color: "var(--v-amber)" }}>Still to fill in:</p>
          <ul className="text-xs space-y-0.5" style={{ color: "var(--v-text-muted)" }}>
            {errors.map((e, i) => (
              <li key={i}>• {e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
