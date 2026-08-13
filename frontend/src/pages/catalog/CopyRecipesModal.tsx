/**
 * CopyRecipesModal — Day 10 Part B: copy recipes from a previous event
 * into the current DRAFT event.
 *
 * Frontend-only feature. Writes go through the existing, unmodified
 * POST /event-recipes/bulk (same endpoint "Save all changes" already
 * uses) — no new backend endpoint, no change to bar_supplier_stock_service.py
 * or any depletion/reporting code.
 *
 * Bar identity does not carry across events (see Day 9 investigation), so
 * each source row's bar is remapped to the target event's bar by exact
 * normalised name (trim, collapse whitespace, lowercase — the same rule
 * Day 9B's update_full bar-matching fix uses on the backend, reimplemented
 * here in TS since it's a different runtime). No near-matching: a source
 * bar with no exact match in the target is SKIPPED and named in the
 * preview, never guessed — a wrong recipe silently changes what depletion
 * reports, so ambiguity fails closed. Legacy rows (bar_id === null,
 * "applies to every bar") can't be expressed as a single bar_id either, so
 * they're skipped the same way, reported under their "All bars" name.
 *
 * Never overwrites: rows that already exist in the target (same
 * drink_name + remapped bar_id + supplier_product_id, matching the
 * backend's own dedup key) are skipped, not touched, not replaced. The
 * preview is mandatory — nothing is written until the user confirms.
 */
import { useMemo, useState } from 'react'

import {
  useEventRecipes,
  useBulkCreateEventRecipes,
  extractEventRecipeBulkErrors,
  getEventRecipeErrorCode,
  type EventRecipeCreate,
  type EventRecipeRow,
} from '@/features/event-recipes/hooks'
import type { BarOption } from './RecipeCard'
import { Button } from '@/design-system/components'
import '@/design-system/components/components.css'
import { inputCls, Label } from '@/design-system/wizardForm'

export interface CandidateSourceEvent {
  id: string
  name: string
  status: string
}

interface Props {
  targetEventId: string
  targetEventName: string
  candidateEvents: CandidateSourceEvent[]
  defaultSourceEventId: string | null
  targetRecipeRows: EventRecipeRow[]
  targetBars: BarOption[]
  onClose: () => void
  onCopied: (count: number) => void
}

function normalizeBarName(name: string): string {
  return name.trim().replace(/\s+/g, ' ').toLowerCase()
}

function recipeKey(drinkName: string, barId: string, supplierProductId: string): string {
  return `${drinkName.trim().toLowerCase()}::${barId}::${supplierProductId}`
}

interface CopyPlan {
  toCopy: EventRecipeCreate[]
  skippedNoBarMatch: { drinkName: string; barName: string }[]
  skippedAlreadyExists: number
}

function computeCopyPlan(
  targetEventId: string,
  sourceRows: EventRecipeRow[],
  targetRows: EventRecipeRow[],
  targetBars: BarOption[],
): CopyPlan {
  // First occurrence wins on a target-side name collision — same
  // deterministic tie-break style as the Day 9B backend fix.
  const targetBarIdByNormName = new Map<string, string>()
  for (const b of targetBars) {
    const norm = normalizeBarName(b.name)
    if (!targetBarIdByNormName.has(norm)) targetBarIdByNormName.set(norm, b.id)
  }

  const existingKeys = new Set(
    targetRows
      .filter((r) => r.bar_id !== null)
      .map((r) => recipeKey(r.drink_name, r.bar_id as string, r.supplier_product_id)),
  )

  const toCopy: EventRecipeCreate[] = []
  const skippedNoBarMatch: CopyPlan['skippedNoBarMatch'] = []
  const seenInBatch = new Set<string>()
  let skippedAlreadyExists = 0

  for (const row of sourceRows) {
    // Legacy "applies to every bar" rows have no single bar to remap to —
    // skip, never guess which one bar it should become.
    if (row.bar_id === null) {
      skippedNoBarMatch.push({ drinkName: row.drink_name, barName: row.bar_name })
      continue
    }
    const targetBarId = targetBarIdByNormName.get(normalizeBarName(row.bar_name))
    if (!targetBarId) {
      skippedNoBarMatch.push({ drinkName: row.drink_name, barName: row.bar_name })
      continue
    }
    const key = recipeKey(row.drink_name, targetBarId, row.supplier_product_id)
    if (existingKeys.has(key) || seenInBatch.has(key)) {
      skippedAlreadyExists += 1
      continue
    }
    seenInBatch.add(key)
    toCopy.push({
      event_id: targetEventId,
      drink_name: row.drink_name,
      bar_id: targetBarId,
      supplier_product_id: row.supplier_product_id,
      ml_per_sale: row.ml_per_sale,
      is_optional: row.is_optional,
    })
  }

  return { toCopy, skippedNoBarMatch, skippedAlreadyExists }
}

export function CopyRecipesModal({
  targetEventId,
  targetEventName,
  candidateEvents,
  defaultSourceEventId,
  targetRecipeRows,
  targetBars,
  onClose,
  onCopied,
}: Props) {
  const [sourceEventId, setSourceEventId] = useState<string | null>(defaultSourceEventId)
  const sourceRecipesQuery = useEventRecipes(sourceEventId)
  const bulkMutation = useBulkCreateEventRecipes(targetEventId)
  const [error, setError] = useState<string | null>(null)

  const sourceEvent = candidateEvents.find((e) => e.id === sourceEventId) ?? null

  const plan = useMemo<CopyPlan | null>(() => {
    if (!sourceRecipesQuery.data) return null
    return computeCopyPlan(targetEventId, sourceRecipesQuery.data.rows, targetRecipeRows, targetBars)
  }, [sourceRecipesQuery.data, targetRecipeRows, targetBars, targetEventId])

  const skippedBarNames = useMemo(
    () => plan ? [...new Set(plan.skippedNoBarMatch.map((s) => s.barName))] : [],
    [plan],
  )

  const handleConfirm = async () => {
    if (!plan || plan.toCopy.length === 0) return
    setError(null)
    try {
      const created = await bulkMutation.mutateAsync({ event_id: targetEventId, rows: plan.toCopy })
      onCopied(created.length)
    } catch (err) {
      const items = extractEventRecipeBulkErrors(err)
      if (items) {
        setError(`${items.length} row${items.length === 1 ? '' : 's'} were rejected — nothing was copied.`)
      } else {
        const code = getEventRecipeErrorCode(err)
        setError(
          code === 'event_not_draft'
            ? 'This event is no longer DRAFT — refresh and re-check.'
            : 'Copy failed — nothing was written. Try again.',
        )
      }
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div
        className="rounded-2xl max-w-lg w-[90%] mx-4 p-6"
        style={{ background: 'var(--v-surface-raised)', border: '0.5px solid var(--v-border)' }}
      >
        <h3 className="text-lg font-medium mb-1" style={{ color: 'var(--v-text)' }}>Copy recipes</h3>
        <p className="text-sm mb-4" style={{ color: 'var(--v-text-muted)' }}>
          Into <span style={{ color: 'var(--v-text)' }}>{targetEventName}</span>
        </p>

        <div className="mb-4">
          <Label>Source event</Label>
          <select
            className={inputCls}
            value={sourceEventId ?? ''}
            onChange={(e) => { setSourceEventId(e.target.value || null); setError(null) }}
          >
            {candidateEvents.length === 0 && <option value="">No other events</option>}
            {candidateEvents.map((ev) => (
              <option key={ev.id} value={ev.id}>{ev.name} — {ev.status.toUpperCase()}</option>
            ))}
          </select>
        </div>

        {sourceEventId && sourceRecipesQuery.isLoading && (
          <p className="text-sm mb-4" style={{ color: 'var(--v-text-muted)' }}>Checking {sourceEvent?.name ?? 'source event'}…</p>
        )}

        {sourceEventId && sourceRecipesQuery.isError && (
          <p className="text-sm mb-4" style={{ color: 'var(--v-pink)' }}>Could not load that event's recipes.</p>
        )}

        {plan && (
          <div className="space-y-2 mb-5">
            <p className="text-sm" style={{ color: plan.toCopy.length > 0 ? 'var(--v-text)' : 'var(--v-text-muted)' }}>
              {plan.toCopy.length === 0
                ? 'Nothing to copy — no eligible recipes from this event.'
                : `${plan.toCopy.length} recipe${plan.toCopy.length === 1 ? '' : 's'} will be copied.`}
            </p>

            {skippedBarNames.length > 0 && (
              <div className="text-sm" style={{ color: 'var(--v-amber)' }}>
                {plan.skippedNoBarMatch.length} skipped — no matching bar in this event:
                <ul className="list-disc list-inside mt-1 text-xs">
                  {skippedBarNames.map((name) => <li key={name}>{name}</li>)}
                </ul>
              </div>
            )}

            {plan.skippedAlreadyExists > 0 && (
              <p className="text-sm" style={{ color: 'var(--v-amber)' }}>
                {plan.skippedAlreadyExists} skipped — already present in this event.
              </p>
            )}
          </div>
        )}

        {error && (
          <p className="text-sm mb-4" style={{ color: 'var(--v-pink)' }}>{error}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {plan && plan.toCopy.length > 0 && (
            <Button variant="primary" onClick={handleConfirm} disabled={bulkMutation.isPending}>
              {bulkMutation.isPending ? 'Copying…' : `Copy ${plan.toCopy.length}`}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
