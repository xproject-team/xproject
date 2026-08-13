/**
 * RecipeCard — one card per drink product in the event-scoped recipe
 * editor (Catalog > Recipes tab, Chunk 2 part 2).
 *
 * Two sections, split by is_optional:
 *   - "Alcohol base" (required)   — blocks depletion math if empty
 *   - "Mixers & extras" (optional) — nice-to-track, never blocks
 * Each section collapses to a single "+ Add" line when it has no rows,
 * rather than a full empty panel (Day 10B layout rebuild) — "Alcohol
 * base" keeps its amber tint when collapsed-and-empty since that state
 * still means depletion math is blocked; "Mixers & extras" collapses
 * to a plain neutral line since it's never blocking.
 *
 * Row editability rules (driven by the backend contract, Chunk 2 part 1):
 *   - SAVED rows: bar + bottle are immutable once created (PATCH only
 *     supports ml_per_sale/is_optional) — shown as static text. ml is
 *     editable inline; edits are staged in the parent's dirtyEdits map
 *     and flushed on "Save all changes".
 *   - LEGACY rows (bar_id === null — seeded before the Sundance 15
 *     editor, meant "applies to every bar"): fully read-only, no ml
 *     edit either. Badged "legacy". Omar deletes + re-adds per-bar if
 *     he wants to touch one.
 *   - DRAFT (new, unsaved) rows: bar dropdown, bottle picker, and ml
 *     input are all editable; removing one is a pure client-side undo
 *     (no API call — it was never saved).
 *
 * Row layout (Day 10B): a fixed 4-track grid — bar / bottle / qty /
 * delete — shared identically between SavedRow and DraftRowView so a
 * card's rows stay visually aligned regardless of which kind they are.
 * Bar column is fixed-width and never truncates (bar names are short in
 * practice). Bottle column is flexible and, for SAVED rows (plain text
 * we fully control), truncates from the MIDDLE when it overflows —
 * "ABSOLUT 1L…VODKA" instead of "ABSOLUT 1L…" — since the trailing
 * category word is often what distinguishes two similar bottles. Draft
 * rows use a native <select>, whose closed-box rendering isn't ours to
 * truncate; it gets the same flexible width plus a title tooltip with
 * the full name, which is the most control a native select allows.
 *
 * NOTE (Day 10 Part A): the backend's EventRecipeRow response has no
 * product_id field, so a per-row "no product linked" signal (the silent
 * depletion gap flagged in the Day 10 brief) cannot be surfaced here
 * without a backend schema change — out of scope for this UI-only pass.
 * See the Day 10 report for what that change would need to be.
 */
import { useEffect, useRef } from 'react'

import type { EventRecipePatch, EventRecipeRow } from '@/features/event-recipes/hooks'
import { Badge } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls } from '@/design-system/wizardForm'

export interface DraftRow {
  client_id: string
  drink_name: string
  bar_id: string
  supplier_product_id: string
  ml_per_sale: number
  is_optional: boolean
}

export interface BarOption {
  id: string
  name: string
}

export interface BottleOption {
  id: string
  name: string
}

interface Props {
  drinkName: string
  savedRows: EventRecipeRow[]
  draftRows: DraftRow[]
  draftRowErrors: Record<string, string>
  dirtyEdits: Record<string, EventRecipePatch>
  bars: BarOption[]
  bottleOptions: BottleOption[]
  readOnly: boolean
  onAddDraftRow: (
    section: 'required' | 'optional',
    overrides?: Partial<Pick<DraftRow, 'bar_id' | 'supplier_product_id' | 'ml_per_sale'>>,
  ) => void
  onUpdateDraftRow: (clientId: string, patch: Partial<DraftRow>) => void
  onRemoveDraftRow: (clientId: string) => void
  onEditSavedRow: (rowId: string, patch: EventRecipePatch) => void
  onDeleteSavedRow: (rowId: string) => void
}

// ─── Row grid — shared by SavedRow and DraftRowView so both kinds of
// row line up in the same card. Bar fixed, bottle flexible, qty fixed
// (room for 4 digits + unit), delete a small fixed icon column.
const ROW_GRID_STYLE: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '140px 1fr 108px 28px',
  gap: '12px',
  alignItems: 'center',
  paddingTop: 8,
  paddingBottom: 8,
}

function truncateMiddle(name: string, maxLen: number): string {
  if (name.length <= maxLen) return name
  const keepStart = Math.ceil((maxLen - 1) * 0.6)
  const keepEnd = Math.floor((maxLen - 1) * 0.4)
  return `${name.slice(0, keepStart)}…${name.slice(name.length - keepEnd)}`
}

function RemoveIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

function RemoveButton({ onClick, title, ariaLabel }: { onClick: () => void; title: string; ariaLabel: string }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center justify-center rounded p-1 transition-colors"
      style={{ color: 'var(--v-text-dim)' }}
      onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--v-pink)'; e.currentTarget.style.background = 'rgba(255, 61, 113, 0.08)' }}
      onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--v-text-dim)'; e.currentTarget.style.background = 'transparent' }}
      title={title}
      aria-label={ariaLabel}
    >
      <RemoveIcon />
    </button>
  )
}

// ─── Auto-suggest keyword matching ─────────────────────────────────────
// Tokenize both the drink name and each candidate bottle's item_name,
// dropping size suffixes (1LT, 70CL, 75CL, ...) and generic descriptor
// words, then look for any overlapping token. First match wins — this
// is a starting point for Omar, not a guarantee.
const SIZE_SUFFIX_RE = /^\d+(\.\d+)?(LT|CL|ML|L)$/i
const GENERIC_WORDS = new Set([
  'BITTER', 'LONDON', 'DRY', 'PREMIUM', 'CLASSICO', 'EXTRA', 'ORIGINAL',
  'RISERVA', 'SPECIAL', 'GOLD', 'BLU', 'BLUE', 'WHITE', 'RED', 'OLD', 'NEW',
])

function tokenize(name: string): string[] {
  return name
    .toUpperCase()
    .split(/\s+/)
    .filter(Boolean)
    .filter((tok) => !SIZE_SUFFIX_RE.test(tok))
    .filter((tok) => !GENERIC_WORDS.has(tok))
}

function findAutoSuggestMatch(
  drinkName: string, candidates: BottleOption[],
): BottleOption | null {
  const drinkTokens = new Set(tokenize(drinkName))
  if (drinkTokens.size === 0) return null
  for (const candidate of candidates) {
    const candidateTokens = tokenize(candidate.name)
    if (candidateTokens.some((t) => drinkTokens.has(t))) return candidate
  }
  return null
}

export function RecipeCard({
  drinkName,
  savedRows,
  draftRows,
  draftRowErrors,
  bars,
  bottleOptions,
  readOnly,
  dirtyEdits,
  onAddDraftRow,
  onUpdateDraftRow,
  onRemoveDraftRow,
  onEditSavedRow,
  onDeleteSavedRow,
}: Props) {
  const savedRequired = savedRows.filter((r) => !r.is_optional)
  const savedOptional = savedRows.filter((r) => r.is_optional)
  const draftRequired = draftRows.filter((r) => !r.is_optional)
  const draftOptional = draftRows.filter((r) => r.is_optional)

  const totalCount = savedRows.length + draftRows.length

  // Auto-suggest: only on this card's first mount (key={drinkName} in
  // the parent guarantees a fresh instance per drink), and only if the
  // Alcohol base section is completely empty.
  const hasSuggestedRef = useRef(false)
  useEffect(() => {
    if (hasSuggestedRef.current || readOnly) return
    hasSuggestedRef.current = true
    if (savedRequired.length > 0 || draftRequired.length > 0) return
    const match = findAutoSuggestMatch(drinkName, bottleOptions)
    if (!match) return
    const defaultBar = bars[0]?.id
    if (!defaultBar) return
    onAddDraftRow('required', {
      bar_id: defaultBar, supplier_product_id: match.id, ml_per_sale: 45,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      className="flex flex-col h-full p-4"
      style={{ background: 'var(--v-surface)', border: '0.5px solid var(--v-border)', borderRadius: 'var(--v-radius)' }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--v-text)' }}>{drinkName}</h3>
        <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>
          {totalCount === 0 ? 'Nothing here yet' : `${totalCount} ingredient${totalCount === 1 ? '' : 's'}`}
        </span>
      </div>

      <Section
        title="Alcohol base"
        rowCount={savedRequired.length + draftRequired.length}
        emptyIsWarning
        muted={false}
        readOnly={readOnly}
        addLabel="+ Add alcohol"
        onAdd={() => onAddDraftRow('required')}
      >
        {savedRequired.map((row) => (
          <SavedRow
            key={row.id}
            row={row}
            pendingEdit={dirtyEdits[row.id]}
            readOnly={readOnly}
            onEdit={(patch) => onEditSavedRow(row.id, patch)}
            onDelete={() => onDeleteSavedRow(row.id)}
          />
        ))}
        {draftRequired.map((row) => (
          <DraftRowView
            key={row.client_id}
            row={row}
            bars={bars}
            bottleOptions={bottleOptions}
            error={draftRowErrors[row.client_id]}
            onUpdate={(patch) => onUpdateDraftRow(row.client_id, patch)}
            onRemove={() => onRemoveDraftRow(row.client_id)}
          />
        ))}
      </Section>

      <div className="mt-2">
        <Section
          title="Mixers & extras"
          rowCount={savedOptional.length + draftOptional.length}
          emptyIsWarning={false}
          muted
          readOnly={readOnly}
          addLabel="+ Add mixer"
          onAdd={() => onAddDraftRow('optional')}
        >
          {savedOptional.map((row) => (
            <SavedRow
              key={row.id}
              row={row}
              pendingEdit={dirtyEdits[row.id]}
              readOnly={readOnly}
              onEdit={(patch) => onEditSavedRow(row.id, patch)}
              onDelete={() => onDeleteSavedRow(row.id)}
            />
          ))}
          {draftOptional.map((row) => (
            <DraftRowView
              key={row.client_id}
              row={row}
              bars={bars}
              bottleOptions={bottleOptions}
              error={draftRowErrors[row.client_id]}
              onUpdate={(patch) => onUpdateDraftRow(row.client_id, patch)}
              onRemove={() => onRemoveDraftRow(row.client_id)}
            />
          ))}
        </Section>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// A group with rows renders as a full panel (title + rows + an "+ Add"
// line at the bottom, if not read-only). A group with zero rows
// collapses to a single line — the "+ Add" button itself when
// editable, or just the quiet title when read-only — instead of an
// empty panel that wastes most of the card.
function Section({
  title, rowCount, emptyIsWarning, muted, readOnly, addLabel, onAdd, children,
}: {
  title: string
  rowCount: number
  emptyIsWarning: boolean
  muted: boolean
  readOnly: boolean
  addLabel: string
  onAdd: () => void
  children: React.ReactNode
}) {
  const isEmpty = rowCount === 0

  if (isEmpty) {
    const tint = emptyIsWarning
      ? { background: 'rgba(255, 216, 77, 0.08)', border: '0.5px solid var(--v-amber)', color: 'var(--v-amber)' }
      : { background: 'transparent', border: '1px dashed var(--v-border)', color: 'var(--v-text-dim)' }
    if (readOnly) {
      return (
        <div
          className="rounded-[var(--v-radius-sm)] px-3 py-2 text-xs font-semibold"
          style={{ background: tint.background, border: tint.border, color: tint.color }}
        >
          {title} — none
        </div>
      )
    }
    return (
      <button
        onClick={onAdd}
        className="w-full rounded-[var(--v-radius-sm)] px-3 py-2 text-xs font-semibold text-left transition-colors"
        style={{ background: tint.background, border: tint.border, color: tint.color }}
      >
        {addLabel}
      </button>
    )
  }

  return (
    <div
      className="rounded-[var(--v-radius-sm)] p-3"
      style={{ background: muted ? 'var(--v-surface-raised)' : 'transparent', border: '0.5px solid var(--v-border)' }}
    >
      <p className="text-xs font-semibold mb-1" style={{ color: muted ? 'var(--v-text-dim)' : 'var(--v-text-muted)' }}>
        {title}
      </p>
      <div>
        {children}
      </div>
      {!readOnly && (
        <button
          onClick={onAdd}
          className="mt-2 text-xs font-semibold px-3 py-1.5 rounded-[var(--v-radius-sm)] w-full transition-colors"
          style={{ color: muted ? 'var(--v-text-muted)' : 'var(--v-cyan)', border: '1px dashed var(--v-border)' }}
        >
          {addLabel}
        </button>
      )}
    </div>
  )
}

// ─── Saved row (bar_id set — editable ml only) ────────────────────────
function SavedRow({
  row, pendingEdit, readOnly, onEdit, onDelete,
}: {
  row: EventRecipeRow
  pendingEdit: EventRecipePatch | undefined
  readOnly: boolean
  onEdit: (patch: EventRecipePatch) => void
  onDelete: () => void
}) {
  const isLegacy = row.bar_id === null
  // Show what the user typed (staged in the parent's dirtyEdits) if there
  // is one, else fall back to the server value — the save path itself
  // (dirtyEdits -> PATCH on "Save all changes") is untouched, this only
  // fixes what the controlled input displays while it's being edited.
  const displayMl = pendingEdit?.ml_per_sale ?? row.ml_per_sale

  return (
    <div style={ROW_GRID_STYLE}>
      <div className="flex items-center gap-1.5 min-w-0">
        <Badge variant="neutral">{row.bar_name}</Badge>
        {isLegacy && <Badge variant="warning">legacy</Badge>}
      </div>
      <div className="text-sm min-w-0" style={{ color: 'var(--v-text)' }} title={row.supplier_product_name}>
        {truncateMiddle(row.supplier_product_name, 30)}
      </div>
      <div className="flex items-center justify-end gap-1.5">
        {isLegacy ? (
          <span className="text-sm" style={{ color: 'var(--v-text-muted)' }}>{row.ml_per_sale} ml</span>
        ) : (
          <>
            <input
              type="number"
              min={1}
              step={1}
              className={`${inputCls} text-right`}
              style={{ width: 64 }}
              value={displayMl}
              disabled={readOnly}
              onChange={(e) => onEdit({ ml_per_sale: Math.max(1, Number(e.target.value) || 1) })}
            />
            <span className="text-xs shrink-0" style={{ color: 'var(--v-text-dim)' }}>ml</span>
          </>
        )}
      </div>
      <div className="flex justify-end">
        {!readOnly && (
          <RemoveButton
            onClick={onDelete}
            title={isLegacy ? 'Delete this legacy rule' : 'Delete'}
            ariaLabel={`Remove ${row.supplier_product_name}`}
          />
        )}
      </div>
    </div>
  )
}

// ─── Draft (new, unsaved) row — fully editable ────────────────────────
function DraftRowView({
  row, bars, bottleOptions, error, onUpdate, onRemove,
}: {
  row: DraftRow
  bars: BarOption[]
  bottleOptions: BottleOption[]
  error?: string
  onUpdate: (patch: Partial<DraftRow>) => void
  onRemove: () => void
}) {
  const selectedBottleName = bottleOptions.find((o) => o.id === row.supplier_product_id)?.name ?? ''

  return (
    <div className="py-2">
      <div style={ROW_GRID_STYLE}>
        <select
          className={inputCls}
          style={{ width: 140 }}
          value={row.bar_id}
          onChange={(e) => onUpdate({ bar_id: e.target.value })}
        >
          <option value="">— select bar —</option>
          {bars.map((b) => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        <select
          className={inputCls}
          value={row.supplier_product_id}
          onChange={(e) => onUpdate({ supplier_product_id: e.target.value })}
          title={selectedBottleName}
        >
          <option value="">— select bottle —</option>
          {bottleOptions.map((o) => (
            <option key={o.id} value={o.id}>{o.name}</option>
          ))}
        </select>
        <div className="flex items-center justify-end gap-1.5">
          <input
            type="number"
            min={1}
            step={1}
            className={`${inputCls} text-right`}
            style={{ width: 64 }}
            value={row.ml_per_sale}
            onChange={(e) => onUpdate({ ml_per_sale: Math.max(1, Number(e.target.value) || 1) })}
          />
          <span className="text-xs shrink-0" style={{ color: 'var(--v-text-dim)' }}>ml</span>
        </div>
        <div className="flex justify-end">
          <RemoveButton onClick={onRemove} title="Remove" ariaLabel="Remove unsaved row" />
        </div>
      </div>
      {error && <p className="text-xs mt-1" style={{ color: 'var(--v-pink)' }}>{error}</p>}
    </div>
  )
}
