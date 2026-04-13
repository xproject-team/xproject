/**
 * useChat — TanStack Query + mutation hooks for the AI assistant chat interface.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export function useChatHistory(eventId: string | null) {
  return useQuery({
    queryKey: ['chat', eventId],
    queryFn: async () => {
      const { data } = await api.get('/chat/messages', { params: { event_id: eventId } })
      return data
    },
    enabled: eventId !== null,
  })
}

export function useSendMessage(eventId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (content: string) => {
      const { data } = await api.post('/chat/messages', { content, event_id: eventId })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', eventId] }),
  })
}
