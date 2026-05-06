/**
 * TanStack Query hooks for the Recipes API.
 *
 * Backend: app/modules/recipes/router.py — 8 endpoints (recipe header
 * CRUD + per-item add/patch/delete). Schema in schemas.py uses
 * RecipeWithItemsResponse for the GET endpoints (eager-loaded items
 * via selectin so no N+1 queries — see service.py).
 *
 * Pattern matches features/products/hooks.ts exactly.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

// ─── Types (mirror backend Pydantic shapes) ───────────────────────────

export type ProductUnit =
  | 'glass' | 'bottle' | 'can' | 'piece' | 'kg' | 'g'
  | 'l' | 'ml' | 'oz' | 'shot' | 'dash' | 'serving'

export interface RecipeItem {
  id:                    string
  recipe_id:             string
  ingredient_product_id: string
  qty:                   number          // backend serializes Decimal as float
  unit:                  ProductUnit
  note:                  string | null
}

export interface RecipeWithItems {
  id:               string
  drink_product_id: string
  yield_qty:        number
  yield_unit:       ProductUnit
  notes:            string | null
  items:            RecipeItem[]
}

// ─── Request payloads ─────────────────────────────────────────────────

export interface RecipeCreatePayload {
  drink_product_id: string
  yield_qty?:       number
  yield_unit:       ProductUnit
  notes?:           string | null
}

export interface RecipeUpdatePayload {
  yield_qty?:  number
  yield_unit?: ProductUnit
  notes?:      string | null
}

export interface RecipeItemCreatePayload {
  ingredient_product_id: string
  qty:                   number
  unit:                  ProductUnit
  note?:                 string | null
}

export interface RecipeItemUpdatePayload {
  qty?:  number
  unit?: ProductUnit
  note?: string | null
}

// ─── Query keys (hierarchical) ─────────────────────────────────────────

export const recipeKeys = {
  all:    ['recipes'] as const,
  list:   ()           => [...recipeKeys.all, 'list'] as const,
  detail: (id: string) => [...recipeKeys.all, id]      as const,
} as const

// ─── Queries ──────────────────────────────────────────────────────────

/** GET /recipes — list with items eager-loaded. */
export function useRecipes() {
  return useQuery({
    queryKey: recipeKeys.list(),
    queryFn:  async (): Promise<RecipeWithItems[]> => {
      const res = await api.get<RecipeWithItems[]>('/recipes')
      return res.data
    },
    staleTime: 2 * 60 * 1000,
  })
}

/** GET /recipes/{id} — single recipe with its items. */
export function useRecipe(id: string | undefined) {
  return useQuery({
    queryKey: id ? recipeKeys.detail(id) : recipeKeys.all,
    queryFn:  async (): Promise<RecipeWithItems> => {
      const res = await api.get<RecipeWithItems>(`/recipes/${id}`)
      return res.data
    },
    enabled: Boolean(id),
  })
}

// ─── Recipe-header mutations ──────────────────────────────────────────

export function useCreateRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: RecipeCreatePayload): Promise<RecipeWithItems> => {
      const res = await api.post<RecipeWithItems>('/recipes', payload)
      return res.data
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: recipeKeys.all })
      qc.setQueryData(recipeKeys.detail(created.id), created)
    },
  })
}

export function useUpdateRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { id: string; payload: RecipeUpdatePayload }): Promise<RecipeWithItems> => {
      const res = await api.patch<RecipeWithItems>(`/recipes/${args.id}`, args.payload)
      return res.data
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: recipeKeys.all })
      qc.setQueryData(recipeKeys.detail(updated.id), updated)
    },
  })
}

export function useDeleteRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string): Promise<void> => {
      await api.delete(`/recipes/${id}`)
    },
    onSuccess: (_v, id) => {
      qc.invalidateQueries({ queryKey: recipeKeys.all })
      qc.removeQueries({ queryKey: recipeKeys.detail(id) })
    },
  })
}

// ─── Per-item mutations ───────────────────────────────────────────────

export function useAddRecipeItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { recipeId: string; payload: RecipeItemCreatePayload }): Promise<RecipeItem> => {
      const res = await api.post<RecipeItem>(`/recipes/${args.recipeId}/items`, args.payload)
      return res.data
    },
    onSuccess: (_item, args) => {
      // Recipe detail must be refetched so the new item shows up
      qc.invalidateQueries({ queryKey: recipeKeys.detail(args.recipeId) })
      qc.invalidateQueries({ queryKey: recipeKeys.list() })
    },
  })
}

export function useUpdateRecipeItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { itemId: string; recipeId: string; payload: RecipeItemUpdatePayload }): Promise<RecipeItem> => {
      const res = await api.patch<RecipeItem>(`/recipes/items/${args.itemId}`, args.payload)
      return res.data
    },
    onSuccess: (_item, args) => {
      qc.invalidateQueries({ queryKey: recipeKeys.detail(args.recipeId) })
      qc.invalidateQueries({ queryKey: recipeKeys.list() })
    },
  })
}

export function useDeleteRecipeItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { itemId: string; recipeId: string }): Promise<void> => {
      await api.delete(`/recipes/items/${args.itemId}`)
    },
    onSuccess: (_v, args) => {
      qc.invalidateQueries({ queryKey: recipeKeys.detail(args.recipeId) })
      qc.invalidateQueries({ queryKey: recipeKeys.list() })
    },
  })
}


// ─── Atomic create-with-items (F.7b/c) ────────────────────────────────

export interface RecipeItemCreateInPayload {
  ingredient_product_id: string
  qty:                   number
  unit:                  ProductUnit
  note?:                 string | null
}

export interface RecipeWithItemsCreatePayload {
  drink_product_id: string
  yield_qty?:       number
  yield_unit:       ProductUnit
  notes?:           string | null
  display_name?:    string | null
  template_id?:     string | null
  items:            RecipeItemCreateInPayload[]
}

/**
 * POST /recipes/with-items — atomic create of recipe header + ingredients
 * in one DB transaction. Use this from one-page forms; for step-by-step
 * flows use useCreateRecipe + useAddRecipeItem instead.
 */
export function useCreateRecipeWithItems() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: RecipeWithItemsCreatePayload): Promise<RecipeWithItems> => {
      const res = await api.post<RecipeWithItems>('/recipes/with-items', payload)
      return res.data
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: recipeKeys.all })
      qc.setQueryData(recipeKeys.detail(created.id), created)
    },
  })
}

