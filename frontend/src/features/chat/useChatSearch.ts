/**
 * Chat search hook. Uses Postgres FTS via the backend /chat/search endpoint.
 *
 * Returns ranked results across all channels the user can access.
 * Stemming is applied ("running" matches "runs"); empty query returns [].
 */
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'


export interface SearchResultItem {
  message_id:   string
  channel_id:   string
  channel_name: string
  sender_id:    string | null
  sender_name:  string | null
  body:         string
  created_at:   string
  rank:         number
}


/** Hook that fetches search results. Enabled only when query is non-empty. */
export function useChatSearch(query: string, limit = 30) {
  const trimmed = query.trim()
  return useQuery({
    queryKey: ['chatSearch', trimmed, limit],
    queryFn: async () => {
      const res = await api.get<SearchResultItem[]>('/chat/search', {
        params: { q: trimmed, limit },
      })
      return res.data
    },
    enabled: trimmed.length > 0,
    staleTime: 30_000,           // cache for 30s; most searches re-done quickly
  })
}


/** Build a body snippet with <mark> around query terms for display. */
export function highlightMatches(body: string, query: string): string {
  const trimmed = query.trim()
  if (!trimmed) return body

  // Build regex: each word in query becomes a case-insensitive match
  // Limit to first 5 words to avoid pathological queries
  const words = trimmed.split(/\s+/).slice(0, 5).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (words.length === 0) return body

  const re = new RegExp(`(${words.join('|')})`, 'ig')
  return body.replace(re, '<mark>$1</mark>')
}
