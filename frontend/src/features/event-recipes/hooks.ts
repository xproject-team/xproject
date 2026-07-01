/**
 * TanStack Query hooks for /api/v1/event-recipes.
 *
 * Backing the Catalog page's event-scoped recipe editor (Chunk 2 part 2).
 * Mirrors the useCreateFullEvent pattern: typed payloads, query-key
 * invalidation on mutation success, no optimistic writes EXCEPT delete
 * (see useDeleteEventRecipe — the card's "×" button needs to feel instant).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'

import { api } from '@/lib/api'

export interface EventRecipeRow {
  id: string
  event_id: string
  drink_name: string
  /** Null on legacy rows seeded before the Sundance 15 recipe editor
   *  (bar_id was NULL = "applies to every bar"). New rows created via
   *  this UI always have a bar_id. */
  bar_id: string | null
  bar_name: string
  supplier_product_id: string
  supplier_product_name: string
  ml_per_sale: number
  is_optional: boolean
}

export interface EventRecipeListResponse {
  rows: EventRecipeRow[]
  read_only: boolean
}

export interface EventRecipeCreate {
  event_id: string
  drink_name: string
  bar_id: string
  supplier_product_id: string
  ml_per_sale: number
  is_optional: boolean
}

export interface EventRecipePatch {
  ml_per_sale?: number
  is_optional?: boolean
}

export interface EventRecipeItemError {
  index: number
  error: string
}

export const eventRecipeKeys = {
  all: ['event-recipes'] as const,
  list: (eventId: string | null) => ['event-recipes', eventId ?? 'none'] as const,
} as const

export function useEventRecipes(eventId: string | null) {
  return useQuery({
    queryKey: eventRecipeKeys.list(eventId),
    queryFn: async (): Promise<EventRecipeListResponse> => {
      const { data } = await api.get<EventRecipeListResponse>(`/event-recipes/${eventId}`)
      return data
    },
    enabled: Boolean(eventId),
  })
}

export function useCreateEventRecipe(eventId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: EventRecipeCreate): Promise<EventRecipeRow> => {
      const { data } = await api.post<EventRecipeRow>('/event-recipes', payload)
      return data
    },
    onSuccess: () => {
      if (eventId) qc.invalidateQueries({ queryKey: eventRecipeKeys.list(eventId) })
    },
  })
}

export function useUpdateEventRecipe(eventId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (
      args: { id: string; patch: EventRecipePatch },
    ): Promise<EventRecipeRow> => {
      const { data } = await api.patch<EventRecipeRow>(`/event-recipes/${args.id}`, args.patch)
      return data
    },
    onSuccess: () => {
      if (eventId) qc.invalidateQueries({ queryKey: eventRecipeKeys.list(eventId) })
    },
  })
}

export function useDeleteEventRecipe(eventId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(`/event-recipes/${id}`)
    },
    // Optimistic: the card's row disappears immediately. Rolled back
    // in onError if the DELETE actually fails (e.g. event flipped out
    // of DRAFT between page load and click).
    onMutate: async (id: string) => {
      if (!eventId) return { previous: undefined }
      const key = eventRecipeKeys.list(eventId)
      await qc.cancelQueries({ queryKey: key })
      const previous = qc.getQueryData<EventRecipeListResponse>(key)
      if (previous) {
        qc.setQueryData<EventRecipeListResponse>(key, {
          ...previous,
          rows: previous.rows.filter((r) => r.id !== id),
        })
      }
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (eventId && context?.previous) {
        qc.setQueryData(eventRecipeKeys.list(eventId), context.previous)
      }
    },
    onSettled: () => {
      if (eventId) qc.invalidateQueries({ queryKey: eventRecipeKeys.list(eventId) })
    },
  })
}

export function useBulkCreateEventRecipes(eventId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (
      payload: { event_id: string; rows: EventRecipeCreate[] },
    ): Promise<EventRecipeRow[]> => {
      const { data } = await api.post<EventRecipeRow[]>('/event-recipes/bulk', payload)
      return data
    },
    onSuccess: () => {
      if (eventId) qc.invalidateQueries({ queryKey: eventRecipeKeys.list(eventId) })
    },
  })
}

/** Pull the per-row errors out of a 422 from POST /event-recipes/bulk. */
export function extractEventRecipeBulkErrors(err: unknown): EventRecipeItemError[] | null {
  const detail = (err as {
    response?: { data?: { detail?: { error?: string; items?: EventRecipeItemError[] } } }
  })?.response?.data?.detail
  if (detail?.error === 'event_recipes_bulk_validation_failed' && detail.items) {
    return detail.items
  }
  return null
}

/** Single-row error code, e.g. 'row_exists' / 'event_not_draft'. */
export function getEventRecipeErrorCode(err: unknown): string | null {
  if (err instanceof AxiosError && err.response?.data?.detail?.error) {
    return err.response.data.detail.error as string
  }
  return null
}
