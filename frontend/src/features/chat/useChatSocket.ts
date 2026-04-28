/**
 * useChatSocket — subscribes to live chat broadcasts for a given channel.
 *
 * Opens a WebSocket to /api/v1/ws/chat?token=<JWT> and maintains a subscribe/
 * unsubscribe loop as activeChannelId changes. When a message arrives, it's
 * appended to the React Query cache so the UI updates without a refetch.
 *
 * Usage: call once on the Chat page, passing the active channel id. One hook,
 * one socket, handles all channel switches for the page's lifetime.
 */
import { useCallback, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { getToken } from '@/lib/auth'
import { useWebSocket } from '@/lib/ws'
import { chatKeys, type MessageResponse } from './useChat'


interface UseChatSocketArgs {
  activeChannelId: string | null
  currentUserId:   string        // so we skip cache-append for messages we
                                 // already inserted optimistically in usePostMessage
  allChannelIds?:  string[]      // subscribe to all of these for sidebar badges
}

interface IncomingEnvelope {
  type:       string
  channel_id: string
  message?:   MessageResponse
  message_id?: string            // only present on 'message_deleted'
}


export function useChatSocket({ activeChannelId, currentUserId, allChannelIds }: UseChatSocketArgs) {
  void currentUserId  // kept in API for future use; SKIP-self logic moved out (RT-1.8 fix)
  const qc = useQueryClient()
  const subscribedChannelsRef = useRef<Set<string>>(new Set())

  const token = getToken()
  const url   = token ? `/api/v1/ws/chat?token=${encodeURIComponent(token)}` : null

  // Store the message handler in a ref so useWebSocket sees a stable
  // reference and doesn't tear down+recreate the socket on every render.
  // This is THE critical fix — without it, React re-renders spawn new
  // WebSocket connections indefinitely, exhausting Chrome's socket pool
  // and causing massive request delays.
  const handlerRef = useRef<(raw: string) => void>(() => {})

  handlerRef.current = function handleMessage(raw: string) {
    let env: IncomingEnvelope
    try {
      env = JSON.parse(raw)
    } catch {
      return                                           // malformed — ignore
    }

    // ─── New message ─────────────────────────────────────────────
    if (env.type === 'message' && env.message) {
      const msg = env.message

      // Skip if we sent it — usePostMessage already put it in the cache
      // SKIP REMOVED: dedup-by-id below handles self-echoes (fixes RT-1.8 cross-tab push)

      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(env.channel_id),
        (old) => {
          if (!old) return [msg]
          if (old.some((m) => m.id === msg.id)) return old   // dedupe
          return [msg, ...old]
        },
      )
      qc.invalidateQueries({ queryKey: chatKeys.channels() })
      return
    }

    // ─── Edit ────────────────────────────────────────────────────
    if (env.type === 'message_edited' && env.message) {
      const msg = env.message

      // Skip our own edits — useEditMessage already updated the cache
      // SKIP REMOVED: dedup-by-id below handles self-echoes (fixes RT-1.8 cross-tab push)

      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(env.channel_id),
        (old) => old?.map((m) => (m.id === msg.id ? msg : m)) ?? [],
      )
      return
    }

    // ─── Mention (user-scoped, fired regardless of channel) ─────
    if (env.type === 'mention') {
      // Drop both 'mentions' caches so the bell badge re-fetches fresh.
      // Cheap (1 GET ~5KB), and the user expects an instant badge update.
      qc.invalidateQueries({ queryKey: ['mentions'] })
      return
    }

    // ─── Delete ──────────────────────────────────────────────────
    if (env.type === 'message_deleted' && env.message_id) {
      // Remove from the cache for every client that sees the message.
      // (No sender-skip: deletions are broadcast to all, including the
      // deleter who already removed it — filter is idempotent either way.)
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(env.channel_id),
        (old) => old?.filter((m) => m.id !== env.message_id) ?? [],
      )
      qc.invalidateQueries({ queryKey: chatKeys.channels() })
      return
    }
  }

  const stableHandler = useCallback((raw: string) => handlerRef.current(raw), [])
  const { isConnected, send } = useWebSocket(url, { onMessage: stableHandler })

  // Subscription sync: subscribes to EVERY channel the user can see so
  // sidebar badge updates work across the whole list, not just the active one.
  // On reconnect, the ref resets and re-subscribes cleanly.
  useEffect(() => {
    if (!isConnected) {
      subscribedChannelsRef.current = new Set()
      return
    }

    const wanted = new Set(allChannelIds ?? [])
    if (activeChannelId) wanted.add(activeChannelId)

    const current = subscribedChannelsRef.current

    try {
      // Unsubscribe from channels no longer wanted
      for (const id of current) {
        if (!wanted.has(id)) {
          send(JSON.stringify({ action: 'unsubscribe', channel_id: id }))
          current.delete(id)
        }
      }
      // Subscribe to new wanted channels
      for (const id of wanted) {
        if (!current.has(id)) {
          send(JSON.stringify({ action: 'subscribe', channel_id: id }))
          current.add(id)
        }
      }
    } catch {
      // Socket closed mid-effect. Next isConnected cycle will retry.
    }
  }, [isConnected, activeChannelId, allChannelIds, send])

  return { isConnected }
}
