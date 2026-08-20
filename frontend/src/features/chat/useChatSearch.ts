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


/**
 * Split a body into plain/highlighted segments for display.
 *
 * SECURITY: this replaces the old `highlightMatches`, which returned an
 * HTML string (raw body + <mark> tags) rendered via dangerouslySetInnerHTML
 * — a stored XSS: a message containing e.g. `<img src=x onerror=...>`
 * executed in the browser of anyone whose search matched it. Segments are
 * rendered as React text nodes, so message bodies are never interpreted
 * as markup.
 */
export interface HighlightSegment {
  text: string
  match: boolean
}

export function highlightSegments(body: string, query: string): HighlightSegment[] {
  const trimmed = query.trim()
  if (!trimmed) return [{ text: body, match: false }]

  // Each query word becomes a case-insensitive match; regex-escape the
  // words and cap at 5 to avoid pathological queries
  const words = trimmed.split(/\s+/).slice(0, 5).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (words.length === 0) return [{ text: body, match: false }]

  const re = new RegExp(`(${words.join('|')})`, 'ig')
  const segments: HighlightSegment[] = []
  let lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(body)) !== null) {
    if (m.index > lastIndex) segments.push({ text: body.slice(lastIndex, m.index), match: false })
    segments.push({ text: m[0], match: true })
    lastIndex = m.index + m[0].length
    if (m[0].length === 0) re.lastIndex++ // safety against zero-width loops
  }
  if (lastIndex < body.length) segments.push({ text: body.slice(lastIndex), match: false })
  return segments
}
