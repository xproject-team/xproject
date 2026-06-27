/**
 * Wizard Step 4 — Recharge
 *
 * Captures the two pieces of recharge configuration that don\'t fit in
 * the regular bars editor:
 *
 *   1) Recharge stations (where guests top up their wristbands).
 *      Stored in state.bars with bar_type=\'recharge\'; this UI is just a
 *      filtered view of that list. Per row: name + device count + Slesh
 *      shop linkage. The SleshShopPicker auto-suggests \'Accrediti\' via
 *      excelHint, which is the production recharge shop in Sundance.
 *
 *   2) Top-up denominations — the preset amounts users (and staff via
 *      override) can load. Two integer lists, comma-separated input.
 *      Pre-filled from the Excel \'2. Parametri\' sheet when uploaded.
 *
 * Design choices:
 *   - Recharge bars share the BarDraft shape with drink/food bars. Step
 *     10 finalize iterates state.bars uniformly; no special-casing.
 *   - Empty state shows \'+ Add recharge station\' with default name
 *     \'Recharge\' and an excelHint baked in so the picker pre-suggests
 *     the right shop even without an Excel upload.
 *   - Denominations input is text (CSV of ints) — same UX as the
 *     existing event-create page so Omar\'s muscle memory carries over.
 *   - Validation hint: count of unlinked recharge stations.
 */
import { useMemo } from "react"

import { SleshShopPicker } from "../SleshShopPicker"
import type { WizardState, BarDraft } from "../types"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
}

// Re-use the same style tokens as Step 1/3 so the wizard looks unified.
const inputCls =
  "w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#1A202C] focus:outline-none focus:ring-2 focus:ring-[#3182CE]/30 focus:border-[#3182CE]"

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-semibold text-[#4A5568] mb-1">{children}</label>
}

function makeClientId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `bd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

// ── Denomination CSV helpers ────────────────────────────────────────
// Stored shape: number[]. Edited shape: "10, 20, 50, 100" string.
// The CSV parsing is intentionally lax: empty entries skipped, any
// non-positive number filtered. Negative numbers don\'t make sense
// for a top-up amount.
function denomsToCsv(d: number[]): string {
  return d.length === 0 ? "" : d.join(", ")
}

function csvToDenoms(csv: string): number[] {
  return csv
    .split(",")
    .map((x) => x.trim())
    .filter((x) => x.length > 0)
    .map((x) => Number(x))
    .filter((n) => Number.isFinite(n) && n > 0)
    .map((n) => Math.round(n))
}

export function WizardStep4Recharge({ state, onChange }: Props) {
  // Recharge bars are a filtered view of state.bars.
  const rechargeBars = useMemo(
    () => state.bars.filter((b) => b.bar_type === "recharge"),
    [state.bars],
  )

  // ── Recharge bar mutations ─────────────────────────────────────────
  const updateBar = (clientId: string, patch: Partial<BarDraft>) => {
    onChange({
      bars: state.bars.map((b) =>
        b.client_id === clientId ? { ...b, ...patch } : b,
      ),
    })
  }

  const removeBar = (clientId: string) => {
    onChange({ bars: state.bars.filter((b) => b.client_id !== clientId) })
  }

  const addBar = () => {
    const newBar: BarDraft = {
      client_id: makeClientId(),
      name: "Recharge",
      device_count: 1,
      bar_type: "recharge",
      slesh_shop_id: null,
      // Bake in the hint so the picker suggests \'Accrediti\' even
      // when there\'s no Excel upload behind this row.
      from_excel: {
        name: "Accrediti",
        device_count: 1,
        bar_type: "recharge",
        notes: null,
      },
    }
    onChange({ bars: [...state.bars, newBar] })
  }

  // ── Denomination handlers ──────────────────────────────────────────
  const setUserDenoms = (csv: string) => {
    onChange({ topup_denominations_user: csvToDenoms(csv) })
  }
  const setStaffDenoms = (csv: string) => {
    onChange({ topup_denominations_staff: csvToDenoms(csv) })
  }

  // ── Validation hints ───────────────────────────────────────────────
  const unlinkedCount = useMemo(
    () => rechargeBars.filter((b) => !b.slesh_shop_id).length,
    [rechargeBars],
  )

  return (
    <div className="space-y-6">
      {/* ── Section 1: Recharge stations ─────────────────────────── */}
      <div className="bg-white border border-[#E2E8F0] rounded-lg p-6">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-[#1A202C]">Recharge stations</h3>
          <p className="text-sm text-[#718096] mt-1">
            Where guests load credit onto their wristbands. Most events have one
            station inside plus optionally one at the entrance. Each station
            links to a Slesh shop so top-up transactions route correctly.
          </p>
        </div>

        {rechargeBars.length === 0 ? (
          <div className="text-center py-8 border-2 border-dashed border-[#E2E8F0] rounded-lg">
            <p className="text-sm text-[#A0AEC0] mb-3">No recharge stations configured.</p>
            <button
              onClick={addBar}
              className="text-sm font-semibold text-[#1E5A8D] hover:text-[#1A4F7F] px-4 py-2 border border-[#CBD5E0] rounded-lg"
            >
              + Add recharge station
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {rechargeBars.map((bar) => (
              <RechargeBarRow
                key={bar.client_id}
                bar={bar}
                onChange={(patch) => updateBar(bar.client_id, patch)}
                onRemove={() => removeBar(bar.client_id)}
              />
            ))}
            <button
              onClick={addBar}
              className="w-full text-sm font-semibold text-[#1E5A8D] hover:text-[#1A4F7F] px-4 py-2 border border-dashed border-[#CBD5E0] rounded-lg hover:bg-[#F7FAFC]"
            >
              + Add recharge station
            </button>
          </div>
        )}

        {rechargeBars.length > 0 && unlinkedCount > 0 && (
          <div className="mt-5 p-3 bg-amber-50 border border-amber-200 rounded-lg">
            <p className="text-xs text-amber-900">
              <span className="font-semibold">{unlinkedCount} of {rechargeBars.length} stations</span>{" "}
              not linked to a Slesh shop.
            </p>
          </div>
        )}
      </div>

      {/* ── Section 2: Denominations ─────────────────────────────── */}
      <div className="bg-white border border-[#E2E8F0] rounded-lg p-6">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-[#1A202C]">Top-up denominations</h3>
          <p className="text-sm text-[#718096] mt-1">
            Preset amounts (in euros) shown to users at recharge stations. Staff
            override is the larger set staff can apply when guests want a custom
            amount. Comma-separated integers.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <Label>User-facing (€)</Label>
            <input
              className={inputCls}
              placeholder="10, 20, 50, 100"
              value={denomsToCsv(state.topup_denominations_user)}
              onChange={(e) => setUserDenoms(e.target.value)}
            />
            {state.topup_denominations_user.length > 0 && (
              <p className="mt-1 text-[10px] text-[#A0AEC0]">
                {state.topup_denominations_user.length} preset
                {state.topup_denominations_user.length === 1 ? "" : "s"}
              </p>
            )}
          </div>
          <div>
            <Label>Staff override (€)</Label>
            <input
              className={inputCls}
              placeholder="5, 10, 20, 50, 100, 200"
              value={denomsToCsv(state.topup_denominations_staff)}
              onChange={(e) => setStaffDenoms(e.target.value)}
            />
            {state.topup_denominations_staff.length > 0 && (
              <p className="mt-1 text-[10px] text-[#A0AEC0]">
                {state.topup_denominations_staff.length} preset
                {state.topup_denominations_staff.length === 1 ? "" : "s"}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// RechargeBarRow — one card per recharge station
// Same structure as Step 3\'s BarRow but trimmed: no type selector
// (always recharge) and no name editor by default (defaulted to
// "Recharge"; click to override). Keeps Omar from accidentally setting
// the type to drinks.
// ─────────────────────────────────────────────────────────────────────
interface RowProps {
  bar: BarDraft
  onChange: (patch: Partial<BarDraft>) => void
  onRemove: () => void
}

function RechargeBarRow({ bar, onChange, onRemove }: RowProps) {
  return (
    <div className="border border-[#E2E8F0] rounded-lg p-4 bg-[#F7FAFC]">
      {/* Top row: name | device count | remove */}
      <div className="grid grid-cols-12 gap-3 mb-3">
        <div className="col-span-12 sm:col-span-8">
          <Label>Station name</Label>
          <input
            className={inputCls}
            value={bar.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="Recharge"
          />
        </div>
        <div className="col-span-10 sm:col-span-3">
          <Label>Devices</Label>
          <input
            type="number"
            min={0}
            className={inputCls}
            value={bar.device_count}
            onChange={(e) =>
              onChange({ device_count: Math.max(0, Math.floor(Number(e.target.value) || 0)) })
            }
          />
        </div>
        <div className="col-span-2 sm:col-span-1 flex items-end justify-end">
          <button
            onClick={onRemove}
            className="w-full h-[38px] flex items-center justify-center text-[#E53E3E] hover:bg-red-50 rounded-lg text-lg"
            aria-label={`Remove ${bar.name || "this station"}`}
            title="Remove station"
          >
            ×
          </button>
        </div>
      </div>

      {/* Slesh picker */}
      <div>
        <Label>Slesh shop</Label>
        <SleshShopPicker
          value={bar.slesh_shop_id}
          onChange={(id) => onChange({ slesh_shop_id: id })}
          excelHint={bar.from_excel?.name ?? "Accrediti"}
        />
      </div>
    </div>
  )
}
