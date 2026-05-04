/**
 * TanStack Query hooks for the Products API.
 *
 * Backend: app/modules/products/router.py — full CRUD; soft-delete via
 * is_archived flag (B2 design — products are referenced from recipes
 * and stock_transactions, so hard delete would orphan rows).
 *
 * Pattern matches features/bars/hooks.ts and features/venues/hooks.ts.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ProductRow } from '@/lib/mockData'

export type ProductType = 'drink' | 'food' | 'ingredient' | 'supply'

// ─── Request payloads ─────────────────────────────────────────────

export interface ProductCreatePayload {
  name:                  string
  product_type:          ProductType
  category?:             string | null
  unit:                  string
  default_price_cents?:  number | null
  external_pos_id?:      string | null
}

export interface ProductUpdatePayload {
  name?:                 string
  category?:             string | null
  unit?:                 string
  default_price_cents?:  number | null
  external_pos_id?:      string | null
  is_archived?:          boolean
}

// ─── Query keys ───────────────────────────────────────────────────

export const productKeys = {
  all:    ['products'] as const,
  list:   (includeArchived: boolean) =>
    [...productKeys.all, 'list', includeArchived ? 'all' : 'active'] as const,
  detail: (id: string) => [...productKeys.all, id] as const,
} as const

// ─── Queries ──────────────────────────────────────────────────────

/** GET /products — list. By default backend hides archived. */
export function useProducts(includeArchived = false) {
  return useQuery({
    queryKey: productKeys.list(includeArchived),
    queryFn:  async (): Promise<ProductRow[]> => {
      const url = includeArchived ? '/products?include_archived=true' : '/products'
      const res = await api.get<ProductRow[]>(url)
      return res.data
    },
    staleTime: 2 * 60 * 1000,
  })
}

/** GET /products/{id} — single product. */
export function useProduct(id: string | undefined) {
  return useQuery({
    queryKey: id ? productKeys.detail(id) : productKeys.all,
    queryFn:  async (): Promise<ProductRow> => {
      const res = await api.get<ProductRow>(`/products/${id}`)
      return res.data
    },
    enabled: Boolean(id),
  })
}

// ─── Mutations ────────────────────────────────────────────────────

export function useCreateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ProductCreatePayload): Promise<ProductRow> => {
      const res = await api.post<ProductRow>('/products', payload)
      return res.data
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: productKeys.all })
      qc.setQueryData(productKeys.detail(created.id), created)
    },
  })
}

export function useUpdateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (args: { id: string; payload: ProductUpdatePayload }): Promise<ProductRow> => {
      const res = await api.patch<ProductRow>(`/products/${args.id}`, args.payload)
      return res.data
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: productKeys.all })
      qc.setQueryData(productKeys.detail(updated.id), updated)
    },
  })
}

/** Archive (soft delete via is_archived flag). */
export function useArchiveProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string): Promise<ProductRow> => {
      const res = await api.patch<ProductRow>(`/products/${id}`, { is_archived: true })
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: productKeys.all })
    },
  })
}
