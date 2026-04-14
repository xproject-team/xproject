/**
 * useChat — React Query hooks backed by real /chat/* endpoints.
 *
 * Hooks:
 *   useChannels()                → GET /chat/channels
 *   useChannelMessages(id)       → GET /chat/channels/{id}/messages (newest first)
 *   usePostMessage(channelId)    → POST /chat/channels/{id}/messages (optimistic + invalidate)
 *   useMarkChannelRead(channelId)→ POST /chat/channels/{id}/read     (clears unread)
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query'
import { api } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────

export interface ChannelResponse {
  id:              string
  channel_type:    'bar' | 'dm' | 'general'
  bar_id:          string | null
  name:            string
  unread_count:    number
  last_message_at: string | null       // ISO datetime
}

export interface MessageResponse {
  id:          string
  channel_id:  string
  sender_id:   string | null
  sender_name: string | null
  body:        string
  created_at:  string                   // ISO datetime
  edited_at:   string | null
}

// ─── Query keys ───────────────────────────────────────────────────────

export const chatKeys = {
  all:       ['chat'] as const,
  channels:  () => [...chatKeys.all, 'channels'] as const,
  messages:  (channelId: string) =>
    [...chatKeys.all, 'channel', channelId, 'messages'] as const,
}

// ─── Hooks ────────────────────────────────────────────────────────────

/** List all channels the current user is a member of. */
export function useChannels(
  options?: Omit<UseQueryOptions<ChannelResponse[]>, 'queryKey' | 'queryFn'>,
) {
  return useQuery<ChannelResponse[]>({
    queryKey: chatKeys.channels(),
    queryFn: async () => {
      const res = await api.get<ChannelResponse[]>('/chat/channels')
      return res.data
    },
    ...options,
  })
}

/** Fetch the latest messages for a channel (newest first). */
export function useChannelMessages(
  channelId: string | null,
  limit: number = 50,
) {
  return useQuery<MessageResponse[]>({
    queryKey: channelId ? chatKeys.messages(channelId) : ['chat', 'messages', 'disabled'],
    queryFn: async () => {
      if (!channelId) return []
      const res = await api.get<MessageResponse[]>(
        `/chat/channels/${channelId}/messages`,
        { params: { limit } },
      )
      return res.data
    },
    enabled: channelId !== null,
  })
}

/** Post a new message. Optimistically prepends to the cache, then refetches. */
export function usePostMessage(channelId: string) {
  const qc = useQueryClient()

  return useMutation<MessageResponse, unknown, string>({
    mutationFn: async (body: string) => {
      const res = await api.post<MessageResponse>(
        `/chat/channels/${channelId}/messages`,
        { body },
      )
      return res.data
    },
    onSuccess: (newMsg) => {
      // Append to message cache (newest-first order)
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(channelId),
        (old) => (old ? [newMsg, ...old] : [newMsg]),
      )
      // Refresh channel list (last_message_at changed, unread is 0 for sender)
      qc.invalidateQueries({ queryKey: chatKeys.channels() })
    },
  })
}

/** Mark channel as read: sets last_read_at=now and clears unread count. */
export function useMarkChannelRead(channelId: string) {
  const qc = useQueryClient()

  return useMutation<void>({
    mutationFn: async () => {
      await api.post(`/chat/channels/${channelId}/read`)
    },
    onSuccess: () => {
      // Zero out unread_count in the channel list cache immediately
      qc.setQueryData<ChannelResponse[]>(
        chatKeys.channels(),
        (old) =>
          old?.map((ch) =>
            ch.id === channelId ? { ...ch, unread_count: 0 } : ch,
          ) ?? [],
      )
    },
  })
}
/** Edit an existing message (sender only). Optimistically updates cache. */
export function useEditMessage(channelId: string) {
  const qc = useQueryClient()

  return useMutation<
    MessageResponse,
    unknown,
    { messageId: string; body: string },
    { previous?: MessageResponse[] }
  >({
    mutationFn: async ({ messageId, body }) => {
      const res = await api.patch<MessageResponse>(
        `/chat/messages/${messageId}`,
        { body },
      )
      return res.data
    },
    // Optimistically update the cache BEFORE the request completes.
    onMutate: async ({ messageId, body }) => {
      await qc.cancelQueries({ queryKey: chatKeys.messages(channelId) })
      const previous = qc.getQueryData<MessageResponse[]>(chatKeys.messages(channelId))
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(channelId),
        (old) =>
          old?.map((m) =>
            m.id === messageId
              ? { ...m, body, edited_at: new Date().toISOString() }
              : m,
          ) ?? [],
      )
      return { previous }
    },
    // On error: roll back to the snapshot
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) {
        qc.setQueryData(chatKeys.messages(channelId), ctx.previous)
      }
    },
    // On success: sync with server's authoritative response (fixes clock drift, etc.)
    onSuccess: (updated) => {
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(channelId),
        (old) => old?.map((m) => (m.id === updated.id ? updated : m)) ?? [],
      )
    },
  })
}

/** Delete a message (sender only). Removes from cache. */
export function useDeleteMessage(channelId: string) {
  const qc = useQueryClient()

  return useMutation<void, unknown, string, { previous?: MessageResponse[] }>({
    mutationFn: async (messageId: string) => {
      await api.delete(`/chat/messages/${messageId}`)
    },
    // Optimistically remove from cache immediately
    onMutate: async (messageId) => {
      await qc.cancelQueries({ queryKey: chatKeys.messages(channelId) })
      const previous = qc.getQueryData<MessageResponse[]>(chatKeys.messages(channelId))
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(channelId),
        (old) => old?.filter((m) => m.id !== messageId) ?? [],
      )
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) {
        qc.setQueryData(chatKeys.messages(channelId), ctx.previous)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: chatKeys.channels() })
    },
  })
}

