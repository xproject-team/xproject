/**
 * Wizard Step 3 — Bars
 *
 * Per-bar editor: name, type, device count, Slesh shop linkage.
 * Rows come from state.bars (pre-populated by Step 2 upload, or
 * empty when Omar skips upload).
 *
 * The Slesh shop_id is the critical linkage — once an event goes
 * LIVE, the order ingester routes Slesh sales to XProject bars via
 * bar.slesh_negozio_id (this column). A bar without a Slesh shop_id
 * is configuration debt: when sales arrive, the ingester auto-creates
 * a stub bar (step 4 of phase 4) — works, but means the wizard data
 * gets shadowed by the auto-created row. Hence the validation hint.
 *
 * Design choices:
 *   - One card per bar row, vertical stack. The horizontal table the
 *     existing EventCreatePage uses is dense + hard to scan once the
 *     SleshShopPicker is in the mix (it has its own dropdown that
 *     would overflow rows).
 *   - Footer hint, not hard block — the wizard footer "Save & Continue"
 *     always works. Finalize (step 10) is where hard gates live.
 *   - Adding a bar uses makeClientId() for the React key (matches
 *     specToDraft() in WizardStep2Upload).
 *   - Removing a bar is irreversible from this UI — no undo. Could
 *     add one later if Omar asks for it.
 */
import { useMemo } from "react"

import { SleshShopPicker } from "../SleshShopPicker"
import type { WizardState, BarDraft } from "../types"
import { inputCls, Label, stepCardCls, rowCardCls, warningBannerCls, warningBannerStyle } from "@/design-system/wizardForm"
import { EmptyState } from "@/design-system/components"
import "@/design-system/components/components.css"

interface Props {
  state: WizardState
  onChange: (next: Partial<WizardState>) => void
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

const BAR_TYPES: { value: BarDraft["bar_type"]; label: string }[] = [
  { value: "drinks",   label: "Drinks"   },
  { value: "food",     label: "Food"     },
  { value: "service",  label: "Service"  },
  { value: "recharge", label: "Recharge" },
]

export function WizardStep3Bars({ state, onChange }: Props) {
  const bars = state.bars

  // ── Mutations ────────────────────────────────────────────────────
  const updateBar = (clientId: string, patch: Partial<BarDraft>) => {
    onChange({
      bars: bars.map((b) => (b.client_id === clientId ? { ...b, ...patch } : b)),
    })
  }

  const removeBar = (clientId: string) => {
    onChange({ bars: bars.filter((b) => b.client_id !== clientId) })
  }

  const addBar = () => {
    const newBar: BarDraft = {
      client_id: makeClientId(),
      name: "",
      device_count: 1,
      bar_type: "drinks",
      slesh_shop_id: null,
      from_excel: null,
    }
    onChange({ bars: [...bars, newBar] })
  }

  // ── Validation hint ──────────────────────────────────────────────
  const unlinkedCount = useMemo(
    () => bars.filter((b) => !b.slesh_shop_id).length,
    [bars],
  )

  return (
    <div className={stepCardCls}>
      <div className="mb-4">
        <h3 className="text-base font-medium" style={{ color: "var(--v-text)" }}>Bars</h3>
        <p className="text-sm mt-1" style={{ color: "var(--v-text-muted)" }}>
          Configure each bar that will sell at this event. Each bar should be linked to
          a Slesh shop so live orders route to the right card.
        </p>
      </div>

      {bars.length === 0 ? (
        <div className="text-center py-8 rounded-[var(--v-radius)]" style={{ border: "2px dashed var(--v-border)" }}>
          <EmptyState
            headline="No bars yet"
            body="Add your first bar to get started."
            action={
              <button
                onClick={addBar}
                className="text-sm font-semibold px-4 py-2 rounded-lg"
                style={{ color: "var(--v-cyan)", border: "0.5px solid var(--v-border)" }}
              >
                + Add first bar
              </button>
            }
          />
        </div>
      ) : (
        <div className="space-y-3">
          {bars.map((bar) => (
            <BarRow
              key={bar.client_id}
              bar={bar}
              onChange={(patch) => updateBar(bar.client_id, patch)}
              onRemove={() => removeBar(bar.client_id)}
            />
          ))}
          <button
            onClick={addBar}
            className="w-full text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
            style={{ color: "var(--v-cyan)", border: "1px dashed var(--v-border)" }}
          >
            + Add bar
          </button>
        </div>
      )}

      {bars.length > 0 && unlinkedCount > 0 && (
        <div className={`mt-5 ${warningBannerCls}`} style={warningBannerStyle}>
          <p className="text-xs" style={{ color: "var(--v-text-muted)" }}>
            <span className="font-semibold" style={{ color: "var(--v-amber)" }}>{unlinkedCount} of {bars.length} bars</span>{" "}
            not linked to a Slesh shop. Sales for unlinked bars will create stub bars
            on first order (works, but creates a duplicate row to clean up after).
          </p>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// BarRow — one card per bar
// ─────────────────────────────────────────────────────────────────────
interface BarRowProps {
  bar: BarDraft
  onChange: (patch: Partial<BarDraft>) => void
  onRemove: () => void
}

function BarRow({ bar, onChange, onRemove }: BarRowProps) {
  return (
    <div className={rowCardCls}>
      {/* Top row: name | type | device count | remove */}
      <div className="grid grid-cols-12 gap-3 mb-3">
        <div className="col-span-12 sm:col-span-5">
          <Label>Bar name</Label>
          <input
            className={inputCls}
            value={bar.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. MAIN BAR"
          />
        </div>
        <div className="col-span-6 sm:col-span-3">
          <Label>Type</Label>
          <select
            className={inputCls}
            value={bar.bar_type}
            onChange={(e) => onChange({ bar_type: e.target.value as BarDraft["bar_type"] })}
          >
            {BAR_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-4 sm:col-span-3">
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
            className="w-full h-[38px] flex items-center justify-center rounded-lg text-lg transition-colors"
            style={{ color: "var(--v-pink)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255, 61, 113, 0.08)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            aria-label={`Remove ${bar.name || "this bar"}`}
            title="Remove bar"
          >
            ×
          </button>
        </div>
      </div>

      {/* Slesh picker row */}
      <div>
        <Label>Slesh shop</Label>
        <SleshShopPicker
          value={bar.slesh_shop_id}
          onChange={(id) => onChange({ slesh_shop_id: id })}
          excelHint={bar.from_excel?.name ?? bar.name}
        />
      </div>
    </div>
  )
}
