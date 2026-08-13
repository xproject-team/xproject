/**
 * RecipeCard — one card per drink product in the event-scoped recipe
 * editor (Catalog > Recipes tab, Chunk 2 part 2).
 *
 * Two sections, split by is_optional:
 *   - "Alcohol base" (required)   — blocks depletion math if empty
 *   - "Mixers & extras" (optional) — nice-to-track, never blocks
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
        <span className="text-xs" style={{ color: 'var(--v-text-dim)' }}>{totalCount} ingredient{totalCount === 1 ? '' : 's'}</span>
      </div>

      <Section
        title="Alcohol base"
        emptyHighlight={savedRequired.length + draftRequired.length === 0}
        muted={false}
      >
        {savedRequired.map((row) => (
          <SavedRow
            key={row.id}
            row={row}
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
        {!readOnly && (
          <button
            onClick={() => onAddDraftRow('required')}
            className="mt-1 text-xs font-semibold px-3 py-1.5 rounded-[var(--v-radius-sm)] w-full transition-colors"
            style={{ color: 'var(--v-cyan)', border: '1px dashed var(--v-border)' }}
          >
            + Add alcohol
          </button>
        )}
      </Section>

      <div className="mt-3">
        <Section
          title="Mixers & extras"
          emptyHighlight={false}
          muted
        >
          {savedOptional.map((row) => (
            <SavedRow
              key={row.id}
              row={row}
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
          {!readOnly && (
            <button
              onClick={() => onAddDraftRow('optional')}
              className="mt-1 text-xs font-semibold px-3 py-1.5 rounded-[var(--v-radius-sm)] w-full transition-colors"
              style={{ color: 'var(--v-text-muted)', border: '1px dashed var(--v-border)' }}
            >
              + Add mixer
            </button>
          )}
        </Section>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
function Section({
  title, emptyHighlight, muted, children,
}: {
  title: string
  emptyHighlight: boolean
  muted: boolean
  children: React.ReactNode
}) {
  return (
    <div
      className="rounded-[var(--v-radius-sm)] p-3 space-y-2"
      style={
        emptyHighlight
          ? { background: 'rgba(255, 216, 77, 0.08)', border: '0.5px solid var(--v-amber)' }
          : { background: muted ? 'var(--v-surface-raised)' : 'transparent', border: '0.5px solid var(--v-border)' }
      }
    >
      <p className="text-xs font-semibold" style={{ color: muted ? 'var(--v-text-dim)' : 'var(--v-text-muted)' }}>
        {title}
      </p>
      {children}
    </div>
  )
}

// ─── Saved row (bar_id set — editable ml only) ────────────────────────
function SavedRow({
  row, readOnly, onEdit, onDelete,
}: {
  row: EventRecipeRow
  readOnly: boolean
  onEdit: (patch: EventRecipePatch) => void
  onDelete: () => void
}) {
  const isLegacy = row.bar_id === null

  return (
    <div className="grid grid-cols-12 gap-2 items-center">
      <div className="col-span-5 flex items-center gap-1.5 min-w-0">
        <Badge variant="neutral">
          <span className="truncate max-w-[8rem] inline-block align-bottom" title={row.bar_name}>{row.bar_name}</span>
        </Badge>
        {isLegacy && <Badge variant="warning">legacy</Badge>}
      </div>
      <div className="col-span-4 text-sm truncate" style={{ color: 'var(--v-text)' }} title={row.supplier_product_name}>
        {row.supplier_product_name}
      </div>
      <div className="col-span-2">
        {isLegacy ? (
          <span className="text-sm" style={{ color: 'var(--v-text-muted)' }}>{row.ml_per_sale} ml</span>
        ) : (
          <input
            type="number"
            min={1}
            step={1}
            className={inputCls}
            value={row.ml_per_sale}
            disabled={readOnly}
            onChange={(e) => onEdit({ ml_per_sale: Math.max(1, Number(e.target.value) || 1) })}
          />
        )}
      </div>
      <div className="col-span-1 flex justify-end">
        {!readOnly && (
          <button
            onClick={onDelete}
            className="rounded px-2 py-1 text-sm transition-colors"
            style={{ color: 'var(--v-pink)' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255, 61, 113, 0.08)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            title={isLegacy ? 'Delete this legacy rule' : 'Delete'}
            aria-label={`Remove ${row.supplier_product_name}`}
          >
            ×
          </button>
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
  return (
    <div>
      <div className="grid grid-cols-12 gap-2 items-center">
        <div className="col-span-4">
          <select
            className={inputCls}
            value={row.bar_id}
            onChange={(e) => onUpdate({ bar_id: e.target.value })}
          >
            <option value="">— select bar —</option>
            {bars.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
        </div>
        <div className="col-span-5">
          <select
            className={inputCls}
            value={row.supplier_product_id}
            onChange={(e) => onUpdate({ supplier_product_id: e.target.value })}
          >
            <option value="">— select bottle —</option>
            {bottleOptions.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <input
            type="number"
            min={1}
            step={1}
            className={inputCls}
            value={row.ml_per_sale}
            onChange={(e) => onUpdate({ ml_per_sale: Math.max(1, Number(e.target.value) || 1) })}
          />
        </div>
        <div className="col-span-1 flex justify-end">
          <button
            onClick={onRemove}
            className="rounded px-2 py-1 text-sm transition-colors"
            style={{ color: 'var(--v-pink)' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255, 61, 113, 0.08)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            aria-label="Remove unsaved row"
          >
            ×
          </button>
        </div>
      </div>
      {error && <p className="text-xs mt-1" style={{ color: 'var(--v-pink)' }}>{error}</p>}
    </div>
  )
}
