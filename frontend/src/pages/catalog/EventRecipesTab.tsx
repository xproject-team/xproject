/**
 * EventRecipesTab — Catalog page's "Recipes" tab content (Chunk 2 part 2).
 *
 * Replaces the old (unscoped) RecipesListPage with an event-scoped
 * editor: Omar picks an event, sees one card per drink product on that
 * event, and defines which bottles each drink consumes + how many ml
 * per pour. Backed by /api/v1/event-recipes (Chunk 2 part 1).
 *
 * Save model (driven by the backend contract):
 *   - New rows (added via a card's "+ Add alcohol/mixer") are staged
 *     client-side in `draftRows` and posted together via the atomic
 *     POST /event-recipes/bulk endpoint on "Save all changes".
 *   - Edits to ALREADY-SAVED rows (ml_per_sale only — bar/bottle are
 *     immutable once saved) are staged in `dirtyEdits` and flushed as
 *     individual PATCH calls in the same "Save all changes" click,
 *     since /bulk is add-only and never touches existing rows.
 *   - Deletes are optimistic and fire immediately (see
 *     useDeleteEventRecipe) — no staging, no "Save" needed.
 *
 * Old RecipesListPage.tsx / RecipeCreatePage.tsx are left in place but
 * unlinked from this tab; cleanup is a future ticket.
 */
import { useEffect, useMemo, useState } from 'react'

import { useEvents } from '@/features/events/hooks'
import { useFullEvent } from '@/features/events/useFullEvent'
import { useBars } from '@/features/bars/hooks'
import { useSupplierProducts, useStorageSummary } from '@/features/event_storage/hooks'
import {
  useBulkCreateEventRecipes,
  useDeleteEventRecipe,
  useEventRecipes,
  useUpdateEventRecipe,
  extractEventRecipeBulkErrors,
  getEventRecipeErrorCode,
  type EventRecipeCreate,
  type EventRecipePatch,
} from '@/features/event-recipes/hooks'
import { RecipeCard, type BarOption, type BottleOption, type DraftRow } from './RecipeCard'

function makeClientId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `dr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

const STATUS_PILL: Record<string, string> = {
  draft: 'bg-[#EDF2F7] text-[#4A5568]',
  active: 'bg-blue-50 text-blue-700',
  live: 'bg-green-50 text-green-700',
  completed: 'bg-[#F7FAFC] text-[#A0AEC0]',
}

export function EventRecipesTab() {
  const eventsQuery = useEvents()
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)

  const sortedEvents = useMemo(() => {
    const events = eventsQuery.data ?? []
    return [...events].sort(
      (a, b) => new Date(b.scheduled_at).getTime() - new Date(a.scheduled_at).getTime(),
    )
  }, [eventsQuery.data])

  const hasDraftEvent = useMemo(() => sortedEvents.some((e) => e.status === 'draft'), [sortedEvents])

  // Default selection: most recent DRAFT event, else most recent overall.
  useEffect(() => {
    if (selectedEventId || sortedEvents.length === 0) return
    const draft = sortedEvents.find((e) => e.status === 'draft')
    setSelectedEventId((draft ?? sortedEvents[0]).id)
  }, [sortedEvents, selectedEventId])

  const selectedEvent = sortedEvents.find((e) => e.id === selectedEventId) ?? null
  const isDraft = selectedEvent?.status === 'draft'

  const fullEventQuery = useFullEvent(selectedEventId)
  const barsQuery = useBars(selectedEventId ?? undefined)
  const recipesQuery = useEventRecipes(selectedEventId)
  const storageSummaryQuery = useStorageSummary(selectedEventId ?? undefined)
  const supplierProductsQuery = useSupplierProducts()

  // useCreateEventRecipe (single-row POST) is exported from hooks.ts for
  // parity with the backend's single-row endpoint, but this editor only
  // ever needs the bulk path — every new row is staged and flushed
  // together via "Save all changes".
  const updateMutation = useUpdateEventRecipe(selectedEventId)
  const deleteMutation = useDeleteEventRecipe(selectedEventId)
  const bulkMutation = useBulkCreateEventRecipes(selectedEventId)

  const menuBars: BarOption[] = useMemo(
    () => (barsQuery.data ?? [])
      .filter((b) => b.bar_type === 'drinks' || b.bar_type === 'food')
      .map((b) => ({ id: b.id, name: b.name })),
    [barsQuery.data],
  )

  // Bottle picker: prefer supplier_products already in THIS event's
  // warehouse (storage summary rows); fall back to the full tenant-wide
  // master list if the event hasn't had any stock declared yet (a
  // brand-new DRAFT event with no Warehouse step done yet shouldn't
  // leave Omar with an empty picker).
  const bottleOptions: BottleOption[] = useMemo(() => {
    const fromEvent = (storageSummaryQuery.data?.rows ?? []).map((r) => ({
      id: r.supplier_product_id, name: r.item_name,
    }))
    if (fromEvent.length > 0) return fromEvent
    return (supplierProductsQuery.data ?? []).map((sp) => ({ id: sp.id, name: sp.item_name }))
  }, [storageSummaryQuery.data, supplierProductsQuery.data])

  const drinkProducts = useMemo(
    () => (fullEventQuery.data?.products ?? []).filter((p) => p.product_type === 'drink'),
    [fullEventQuery.data],
  )

  // ── Local unsaved state ─────────────────────────────────────────
  const [draftRows, setDraftRows] = useState<DraftRow[]>([])
  const [dirtyEdits, setDirtyEdits] = useState<Record<string, EventRecipePatch>>({})
  const [draftRowErrors, setDraftRowErrors] = useState<Record<string, string>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  // Switching events discards any unsaved staging — the cards below
  // are for a different event entirely.
  useEffect(() => {
    setDraftRows([])
    setDirtyEdits({})
    setDraftRowErrors({})
    setSaveError(null)
  }, [selectedEventId])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 3000)
    return () => window.clearTimeout(t)
  }, [toast])

  const isDirty = draftRows.length > 0 || Object.keys(dirtyEdits).length > 0
  const isSaving = bulkMutation.isPending || updateMutation.isPending

  function addDraftRow(
    drinkName: string,
    isOptional: boolean,
    overrides?: Partial<Pick<DraftRow, 'bar_id' | 'supplier_product_id' | 'ml_per_sale'>>,
  ) {
    setDraftRows((prev) => [...prev, {
      client_id: makeClientId(),
      drink_name: drinkName,
      bar_id: overrides?.bar_id ?? menuBars[0]?.id ?? '',
      supplier_product_id: overrides?.supplier_product_id ?? bottleOptions[0]?.id ?? '',
      ml_per_sale: overrides?.ml_per_sale ?? 45,
      is_optional: isOptional,
    }])
  }

  function updateDraftRow(clientId: string, patch: Partial<DraftRow>) {
    setDraftRows((prev) => prev.map((r) => (r.client_id === clientId ? { ...r, ...patch } : r)))
  }

  function removeDraftRow(clientId: string) {
    setDraftRows((prev) => prev.filter((r) => r.client_id !== clientId))
    setDraftRowErrors((prev) => {
      const next = { ...prev }
      delete next[clientId]
      return next
    })
  }

  function editSavedRow(rowId: string, patch: EventRecipePatch) {
    setDirtyEdits((prev) => ({ ...prev, [rowId]: { ...prev[rowId], ...patch } }))
  }

  async function deleteSavedRow(rowId: string) {
    try {
      await deleteMutation.mutateAsync(rowId)
      setDirtyEdits((prev) => {
        const next = { ...prev }
        delete next[rowId]
        return next
      })
      setToast('Deleted.')
    } catch {
      setToast('Could not delete — restored.')
    }
  }

  async function handleSaveAll() {
    if (!selectedEventId) return
    setSaveError(null)
    setDraftRowErrors({})
    try {
      if (draftRows.length > 0) {
        const rows: EventRecipeCreate[] = draftRows.map((r) => ({
          event_id: selectedEventId,
          drink_name: r.drink_name,
          bar_id: r.bar_id,
          supplier_product_id: r.supplier_product_id,
          ml_per_sale: r.ml_per_sale,
          is_optional: r.is_optional,
        }))
        await bulkMutation.mutateAsync({ event_id: selectedEventId, rows })
      }
      if (Object.keys(dirtyEdits).length > 0) {
        await Promise.all(
          Object.entries(dirtyEdits).map(([id, patch]) => updateMutation.mutateAsync({ id, patch })),
        )
      }
      setDraftRows([])
      setDirtyEdits({})
      setToast('Saved.')
    } catch (err) {
      const items = extractEventRecipeBulkErrors(err)
      if (items) {
        // Bulk payload rows were built in the same order as draftRows,
        // so index i maps 1:1 onto draftRows[i].
        const byClientId: Record<string, string> = {}
        items.forEach((it) => {
          const row = draftRows[it.index]
          if (row) byClientId[row.client_id] = it.error
        })
        setDraftRowErrors(byClientId)
        setSaveError(`${items.length} row${items.length === 1 ? '' : 's'} could not be saved.`)
      } else {
        const code = getEventRecipeErrorCode(err)
        setSaveError(
          code === 'row_exists'
            ? 'One of these rows already exists.'
            : code === 'event_not_draft'
              ? 'This event is no longer DRAFT — refresh and re-check.'
              : 'Could not save changes.',
        )
      }
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* 1. Event selector + save-all row */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <label className="text-sm font-semibold text-[#4A5568]" htmlFor="recipe-event-select">
            Editing recipes for event:
          </label>
          <select
            id="recipe-event-select"
            className="rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm bg-white text-[#1A202C]"
            value={selectedEventId ?? ''}
            onChange={(e) => setSelectedEventId(e.target.value || null)}
          >
            {sortedEvents.map((ev) => (
              <option key={ev.id} value={ev.id}>
                {ev.name} — {ev.status.toUpperCase()}
              </option>
            ))}
          </select>
          {selectedEvent && (
            <span className={`text-xs font-semibold px-2 py-1 rounded ${STATUS_PILL[selectedEvent.status] ?? 'bg-[#EDF2F7] text-[#4A5568]'}`}>
              {selectedEvent.status.toUpperCase()}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {isDirty && <span className="text-xs text-[#A0AEC0]">Unsaved changes</span>}
          <button
            onClick={handleSaveAll}
            disabled={!isDraft || !isDirty || isSaving}
            className={[
              'px-4 py-2 text-sm font-semibold rounded-lg text-white transition-colors',
              !isDraft || !isDirty || isSaving
                ? 'bg-[#CBD5E0] cursor-not-allowed'
                : 'bg-[#1ABC9C] hover:bg-[#17a589]',
            ].join(' ')}
          >
            {isSaving ? 'Saving…' : 'Save all changes'}
          </button>
        </div>
      </div>

      {!hasDraftEvent && selectedEvent && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-xs text-amber-900">
            No DRAFT events exist. Showing the most recent event for reference.
          </p>
        </div>
      )}

      {/* 2. read-only banner */}
      {selectedEvent && !isDraft && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg">
          <p className="text-sm text-amber-900">
            This event is {selectedEvent.status.toUpperCase()}. Recipes are locked.
            Go to a DRAFT event to make changes.
          </p>
        </div>
      )}

      {saveError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-900">{saveError}</p>
        </div>
      )}

      {/* 3. recipe cards */}
      {!selectedEventId ? (
        <p className="text-sm text-[#A0AEC0]">No events yet.</p>
      ) : drinkProducts.length === 0 ? (
        <p className="text-sm text-[#A0AEC0]">This event has no drink products yet.</p>
      ) : (
        <div className="space-y-4">
          {drinkProducts.map((product) => {
            const savedRows = (recipesQuery.data?.rows ?? []).filter(
              (r) => r.drink_name.trim().toLowerCase() === product.name.trim().toLowerCase(),
            )
            const rowsForDrink = draftRows.filter((r) => r.drink_name === product.name)
            return (
              <RecipeCard
                key={product.name}
                drinkName={product.name}
                savedRows={savedRows}
                draftRows={rowsForDrink}
                draftRowErrors={draftRowErrors}
                bars={menuBars}
                bottleOptions={bottleOptions}
                readOnly={!isDraft}
                onAddDraftRow={(section, overrides) =>
                  addDraftRow(product.name, section === 'optional', overrides)
                }
                onUpdateDraftRow={updateDraftRow}
                onRemoveDraftRow={removeDraftRow}
                onEditSavedRow={editSavedRow}
                onDeleteSavedRow={deleteSavedRow}
              />
            )
          })}
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 bg-[#1A202C] text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}
