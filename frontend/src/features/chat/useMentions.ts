/**
 * useMentions — fetch + manage the current user's mention notifications.
 *
 * Backed by GET /chat/mentions and POST /chat/mentions/{id}/read.
 * Auto-refreshes via React Query staleTime; live updates arrive
 * through the user-scoped WebSocket subscription (see useChatSocket).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'

export interface MentionResponse {
  id:           string
  channel_id:   string
  channel_name: string
  message_id:   string
  sender_name:  string | null
  body:         string
  created_at:   string         // ISO-8601 UTC
  read_at:      string | null  // null = unread
}

export const mentionKeys = {
  all:    ['mentions'] as const,
  list:   (unreadOnly: boolean) => ['mentions', { unreadOnly }] as const,
}


/** Fetch recent mentions for the current user. */
export function useMentions(unreadOnly = false, limit = 50) {
  return useQuery<MentionResponse[]>({
    queryKey: mentionKeys.list(unreadOnly),
    queryFn:  async () => {
      const params = new URLSearchParams({
        unread_only: String(unreadOnly),
        limit:       String(limit),
      })
      const res = await api.get<MentionResponse[]>(`/chat/mentions?${params}`)
      return res.data
    },
    staleTime: 30_000,    // re-fetch on window focus or after 30s
  })
}


/** Mark a single mention as read. Optimistically updates cache. */
export function useMarkMentionRead() {
  const qc = useQueryClient()

  return useMutation<void, unknown, string, { snapshots?: Map<readonly unknown[], MentionResponse[]> }>({
    mutationFn: async (mentionId: string) => {
      await api.post(`/chat/mentions/${mentionId}/read`)
    },
    // Update both cached query variants (unread_only=true and false)
    onMutate: async (mentionId) => {
      await qc.cancelQueries({ queryKey: mentionKeys.all })
      const snapshots = new Map<readonly unknown[], MentionResponse[]>()
      const now = new Date().toISOString()

      for (const [key, data] of qc.getQueriesData<MentionResponse[]>({ queryKey: mentionKeys.all })) {
        if (!data) continue
        snapshots.set(key, data)
        // For the unread-only list, drop the read mention.
        // For the all-mentions list, set read_at on it.
        const [, opts] = key as [string, { unreadOnly: boolean }]
        const updated = opts.unreadOnly
          ? data.filter((m) => m.id !== mentionId)
          : data.map((m) => (m.id === mentionId ? { ...m, read_at: now } : m))
        qc.setQueryData(key, updated)
      }

      return { snapshots }
    },
    onError: (_err, _vars, ctx) => {
      // Roll back all snapshots
      if (ctx?.snapshots) {
        for (const [key, prev] of ctx.snapshots) {
          qc.setQueryData(key, prev)
        }
      }
    },
  })
}
