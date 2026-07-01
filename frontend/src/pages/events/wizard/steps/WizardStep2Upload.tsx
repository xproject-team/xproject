/**
 * Wizard Step 2 — Upload
 *
 * Drag a Slesh project-plan .xlsx in (or click to browse). Calls the
 * /events/import-plan endpoint, shows a preview of what was parsed,
 * lets Omar pick which event date (multi-event Excels cover 4 dates),
 * and writes the result into wizard state for downstream steps to
 * consume.
 *
 * Design principles:
 *   \u2022 Defensive: every error mode has a clear message + a way back
 *   \u2022 Reversible: "Re-upload" always works; never traps the user
 *   \u2022 Optional: "Skip step" lets Omar manually configure if needed
 *   \u2022 Downstream-aware: writes parsed_plan + picked_date + bars +
 *     recharge_device_count so Step 3 + Step 4 are pre-populated
 */
import { useRef, useState } from "react"

import { useImportEventPlan } from "@/features/events/hooks"
import type { WizardState, BarDraft, ProductDraft } from "../types"
import type { ParsedEventPlan, BarSpec, ProductSpec } from "@/lib/eventPlan"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

// Accepted MIME types + the .xlsx extension. We list both because some
// browsers report xlsx as application/octet-stream.
const ACCEPTED =
  ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/octet-stream"

const MAX_BYTES = 2 * 1024 * 1024 // 2 MB — matches backend hard cap

/**
 * Seed a recharge bar from parsed_plan.recharge_device_count.
 *
 * The Excel '3. Device Count' sheet has a row 'Punti di Ricarica' with a
 * device count. We translate that into a single recharge BarDraft so
 * Step 4 already has one row to configure. excelHint = 'Accrediti' makes
 * the Slesh picker auto-suggest the right shop on Sundance.
 */
function seedRechargeBarsFromPlan(deviceCount: number): BarDraft[] {
  if (!deviceCount || deviceCount <= 0) return []
  return [{
    client_id: makeClientIdLocal(),
    name: "Recharge",
    device_count: deviceCount,
    bar_type: "recharge",
    slesh_shop_id: null,
    from_excel: {
      name: "Accrediti",
      device_count: deviceCount,
      bar_type: "recharge",
      notes: "Auto-seeded from Excel 'Punti di Ricarica'",
    },
  }]
}

// Local makeClientId — keeps the helper self-contained. The wizard
// already has one in another file but this avoids a cross-file dep
// for a 4-line helper.
function makeClientIdLocal(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `bd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function WizardStep2Upload({ state, onChange }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [clientError, setClientError] = useState<string | null>(null)
  const importMutation = useImportEventPlan()

  const parsed = state.parsed_plan

  // ── File handling ────────────────────────────────────────────────
  const handleFile = (file: File) => {
    setClientError(null)
    // Client-side guard: file size + extension. We don’t want to spend
    // a network round-trip on something we can reject locally.
    if (file.size > MAX_BYTES) {
      setClientError(`File is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum 2 MB.`)
      return
    }
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setClientError("Only .xlsx files are supported.")
      return
    }
    importMutation.mutate(file, {
      onSuccess: (plan) => {
        applyParsedPlan(plan)
      },
    })
  }

  // ── Apply a successful parse to wizard state ─────────────────────
  // Single source of truth for how parsed data fans out into the
  // downstream wizard steps. Keeping this in one function makes the
  // pre-population behavior easy to audit.
  const applyParsedPlan = (plan: ParsedEventPlan) => {
    const bars: BarDraft[] = [
      ...plan.drink_bars.map(specToDraft),
      ...plan.food_bars.map(specToDraft),
      ...plan.other_bars.map(specToDraft),
      // Recharge bars don\'t come back as a list from the parser (the
      // Excel sheet only gives an aggregate device count). Synthesize a
      // single recharge bar so Step 4 has something to configure rather
      // than starting empty. excelHint is "Accrediti" so the Slesh
      // picker auto-suggests the right shop on Sundance.
      ...seedRechargeBarsFromPlan(plan.recharge_device_count),
    ]
    // Auto-pick the date if the Excel only covers one (no decision needed).
    // Multi-event Excels (4 Sundance dates) require Omar to choose.
    const autoPickedDate = plan.event_dates.length === 1 ? plan.event_dates[0] : null

    // Products, like bars, are fully replaced on (re-)upload.
    const products: ProductDraft[] = plan.products.map(specToProductDraft)

    onChange({
      parsed_plan: parsed_plan_with_skip_cleared(plan),
      picked_date: autoPickedDate,
      bars,
      products,
      recharge_device_count: plan.recharge_device_count,
      // Denominations are event-level (not per-bar); pre-fill from Excel
      // so Omar doesn\'t re-type the standard Sundance amounts (10/20/50/100).
      topup_denominations_user:  plan.topup_denominations_user  ?? [],
      topup_denominations_staff: plan.topup_denominations_staff ?? [],
    })
  }

  // ── Date picker ──────────────────────────────────────────────────
  const handlePickDate = (date: string) => {
    onChange({ picked_date: date })
  }

  // ── Drag-and-drop handlers ───────────────────────────────────────
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()  // required to allow drop
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }

  // ── Re-upload + skip ─────────────────────────────────────────────
  const handleReupload = () => {
    setClientError(null)
    importMutation.reset()
    onChange({
      parsed_plan: null,
      picked_date: null,
      bars: [],
      products: [],
      recharge_device_count: 0,
    })
    if (inputRef.current) inputRef.current.value = ""
  }

  const handleSkip = () => {
    setClientError(null)
    importMutation.reset()
    onChange({
      parsed_plan: null,
      picked_date: null,
      // Don’t wipe bars/recharge — user may have done partial manual work.
    })
  }

  const isLoading = importMutation.isPending
  const serverError =
    importMutation.isError ? (importMutation.error as Error)?.message : null
  const displayError = clientError ?? serverError

  // ── Render ───────────────────────────────────────────────────────
  return (
    <div className="bg-white border border-[#E2E8F0] rounded-lg p-6">
      {!parsed ? (
        <>
          {/* Drop zone */}
          <div
            onClick={() => inputRef.current?.click()}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={[
              "border-2 border-dashed rounded-lg p-12 text-center cursor-pointer transition-colors",
              isDragging
                ? "border-[#1E5A8D] bg-[#F0F4F8]"
                : "border-[#CBD5E0] hover:border-[#1E5A8D] hover:bg-[#F7FAFC]",
              isLoading ? "opacity-60 pointer-events-none" : "",
            ].join(" ")}
          >
            {isLoading ? (
              <div className="flex flex-col items-center gap-2">
                <svg className="w-8 h-8 text-[#1E5A8D] animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <p className="text-sm text-[#4A5568]">Parsing…</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <svg className="w-12 h-12 text-[#A0AEC0]" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="text-base font-semibold text-[#1A202C]">
                  Drop the Slesh plan .xlsx here
                </p>
                <p className="text-sm text-[#718096]">or click to browse</p>
                <p className="text-xs text-[#A0AEC0] mt-2">Max 2 MB · .xlsx only</p>
              </div>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) handleFile(f)
                // Reset so picking the same file again still triggers onChange
                e.target.value = ""
              }}
            />
          </div>

          {/* Skip option */}
          <div className="mt-4 text-center">
            <button
              onClick={handleSkip}
              className="text-sm text-[#718096] hover:text-[#1E5A8D] underline"
            >
              Skip and configure manually
            </button>
          </div>

          {/* Error display */}
          {displayError && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-[#C53030]">{displayError}</p>
            </div>
          )}
        </>
      ) : (
        /* ── Parsed preview ────────────────────────────────────── */
        <ParsedPreview
          plan={parsed}
          pickedDate={state.picked_date}
          onPickDate={handlePickDate}
          onReupload={handleReupload}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────
function makeClientId(): string {
  // crypto.randomUUID requires secure context (https or localhost). It works
  // on localhost in modern browsers but throws in some edge cases (older
  // browsers, file:// origins, sandboxed iframes). Fall back to a
  // Math.random-based id — this is purely a React list key, not a security
  // boundary, so the lower entropy is fine.
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through to fallback */
  }
  return `bd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function specToDraft(spec: BarSpec): BarDraft {
  return {
    client_id: makeClientId(),
    name: spec.name,
    device_count: spec.device_count,
    bar_type: spec.bar_type,
    slesh_shop_id: null,
    from_excel: spec,
  }
}

// ── Product mapping helpers ──────────────────────────────────────────
// Copied from payload.ts rather than imported: payload.ts is finalize-
// time code, and keeping Step 2's Excel-seeding logic self-contained
// avoids a cross-concern dependency between "parse the Excel" and
// "build the POST body".

// Backend's ProductCategory enum — keep in sync with
// app/modules/products/models.py ProductCategory. We map the Excel's
// free-text category strings onto this when possible; otherwise we
// store null and let Omar categorize via the wizard's Products step.
const VALID_PRODUCT_CATEGORIES = new Set([
  "beer_draft", "beer_bottle",
  "basic_cocktail", "premium_cocktail",
  "wine_red", "wine_white", "wine_sparkling",
  "soft_drink",
])

function normalizeCategory(raw: string | null | undefined): ProductDraft["category"] {
  if (!raw) return null
  const norm = raw.trim().toLowerCase().replace(/[\s-]+/g, "_")
  if (VALID_PRODUCT_CATEGORIES.has(norm)) return norm as ProductDraft["category"]
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

function deriveProductType(category: string | null | undefined): ProductDraft["product_type"] {
  const c = (category ?? "").toLowerCase()
  if (c.includes("food") || c.includes("cibo") || c.includes("pizza")) return "food"
  return "drink"
}

function specToProductDraft(spec: ProductSpec): ProductDraft {
  const productType = deriveProductType(spec.category)
  return {
    client_id: makeClientId(),
    name: spec.name.trim(),
    product_type: productType,
    category: productType === "drink" ? normalizeCategory(spec.category) : null,
    // Excel doesn't distinguish food subtypes; Omar edits in the wizard.
    food_type: null,
    // Excel doesn't specify a unit.
    unit: "bottle",
    default_price_cents: spec.price_cents,
    // Excel is percent (10), backend wants a fraction (0.10).
    iva_pct: spec.iva_pct / 100,
    cauzione_cents: spec.cauzione_cents,
    // Let derive_tier_rank compute this on save.
    tier_rank: null,
  }
}

/** A no-op for now — placeholder for future ParsedEventPlan
 *  transformations the wizard may want to apply (normalizing names,
 *  filling defaults, etc). Keeps the call site explicit. */
function parsed_plan_with_skip_cleared(plan: ParsedEventPlan): ParsedEventPlan {
  return plan
}

// ─────────────────────────────────────────────────────────────────────
// ParsedPreview — the post-upload summary card
// ─────────────────────────────────────────────────────────────────────
interface ParsedPreviewProps {
  plan: ParsedEventPlan
  pickedDate: string | null
  onPickDate: (date: string) => void
  onReupload: () => void
}

function ParsedPreview({ plan, pickedDate, onPickDate, onReupload }: ParsedPreviewProps) {
  const dateCount = plan.event_dates.length
  const drinkCount = plan.drink_bars.length
  const foodCount = plan.food_bars.length
  const productCount = plan.products.length
  const warningCount = plan.warnings.length
  const totalDevices =
    plan.drink_bars.reduce((s, b) => s + b.device_count, 0) +
    plan.food_bars.reduce((s, b) => s + b.device_count, 0) +
    plan.other_bars.reduce((s, b) => s + b.device_count, 0)

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <svg className="w-5 h-5 text-[#1ABC9C]" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            <h3 className="text-lg font-bold text-[#1A202C]">
              {plan.event_name ?? "Untitled event"}
            </h3>
          </div>
          {plan.venue_name && (
            <p className="text-sm text-[#718096]">
              {plan.venue_name}
              {plan.capacity ? ` · capacity ${plan.capacity}` : ""}
            </p>
          )}
        </div>
        <button
          onClick={onReupload}
          className="text-sm font-semibold text-[#1E5A8D] hover:text-[#1A4F7F] px-3 py-1.5 border border-[#CBD5E0] rounded-lg"
        >
          Re-upload
        </button>
      </div>

      {/* Date picker */}
      {dateCount > 1 && (
        <div className="mb-5 p-4 bg-[#F0F4F8] rounded-lg">
          <p className="text-sm font-semibold text-[#1A202C] mb-2">
            This plan covers {dateCount} dates. Pick the one this event is for:
          </p>
          <div className="flex flex-wrap gap-2">
            {plan.event_dates.map((d) => (
              <button
                key={d}
                onClick={() => onPickDate(d)}
                className={[
                  "px-3 py-1.5 rounded-lg text-sm font-semibold border transition-colors",
                  pickedDate === d
                    ? "bg-[#1E5A8D] text-white border-[#1E5A8D]"
                    : "bg-white text-[#1E5A8D] border-[#CBD5E0] hover:border-[#1E5A8D]",
                ].join(" ")}
              >
                {d}
              </button>
            ))}
          </div>
          {!pickedDate && (
            <p className="text-xs text-[#C53030] mt-2">
              You’ll need to pick a date before continuing.
            </p>
          )}
        </div>
      )}
      {dateCount === 1 && pickedDate && (
        <div className="mb-5 text-sm text-[#4A5568]">
          Date: <span className="font-semibold text-[#1A202C]">{pickedDate}</span>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Stat label="Drink bars" value={drinkCount} />
        <Stat label="Food trucks" value={foodCount} />
        <Stat label="Devices" value={totalDevices} />
        <Stat label="Products" value={productCount} />
      </div>

      {/* Warnings (collapsed by default — click to expand) */}
      {warningCount > 0 && (
        <details className="mb-5 border border-amber-200 bg-amber-50 rounded-lg">
          <summary className="cursor-pointer px-4 py-2 text-sm font-semibold text-amber-800">
            ⚠ {warningCount} warning{warningCount > 1 ? "s" : ""} — click to review
          </summary>
          <ul className="px-4 pb-3 space-y-1.5">
            {plan.warnings.map((w, i) => (
              <li key={i} className="text-xs text-amber-900">
                <span className="font-semibold">{w.sheet}</span>
                {w.where && w.where !== "(missing)" ? ` (${w.where})` : ""}: {w.message}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-xs text-[#A0AEC0]">
        Steps 3 + 4 are now pre-populated. You can edit anything before finalizing.
      </p>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-[#F7FAFC] border border-[#E2E8F0] rounded-lg p-3">
      <p className="text-2xl font-bold text-[#1A202C] leading-none">{value}</p>
      <p className="text-xs text-[#718096] mt-1.5">{label}</p>
    </div>
  )
}
