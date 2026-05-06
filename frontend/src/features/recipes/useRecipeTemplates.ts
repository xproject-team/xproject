/**
 * Recipe Templates hook — reads the IBA-seeded catalog (read-only).
 *
 * Backend: GET /api/v1/recipes/templates
 * Pattern matches features/products/hooks.ts.
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

export type TemplateCategory =
  | 'contemporary' | 'unforgettable' | 'new_era'
  | 'shooter' | 'wine' | 'beer'

export interface RecipeTemplateItem {
  id:               string
  template_id:      string
  ingredient_role:  string
  ingredient_label: string
  qty:              number
  unit:             string
  order_index:      number
}

export interface RecipeTemplate {
  id:          string
  slug:        string
  name:        string
  category:    TemplateCategory | string
  description: string | null
  glass_type:  string | null
  total_ml:    number | null
  items:       RecipeTemplateItem[]
}

export const recipeTemplateKeys = {
  all:    ['recipe-templates'] as const,
  list:   (category?: string | null) =>
    [...recipeTemplateKeys.all, 'list', category ?? 'all'] as const,
} as const

export function useRecipeTemplates(category?: string | null) {
  return useQuery({
    queryKey: recipeTemplateKeys.list(category),
    queryFn:  async (): Promise<RecipeTemplate[]> => {
      const url = category ? `/recipes/templates?category=${category}` : '/recipes/templates'
      const res = await api.get<RecipeTemplate[]>(url)
      return res.data
    },
    staleTime: 10 * 60 * 1000, // 10 min — IBA catalog rarely changes
  })
}
