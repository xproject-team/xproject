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
}

interface IncomingEnvelope {
  type:       string
  channel_id: string
  message?:   MessageResponse
  message_id?: string            // only present on 'message_deleted'
}


export function useChatSocket({ activeChannelId, currentUserId }: UseChatSocketArgs) {
  const qc = useQueryClient()
  const subscribedRef = useRef<string | null>(null)    // last channel we subscribed to

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
      if (msg.sender_id === currentUserId) return

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
      if (msg.sender_id === currentUserId) return

      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(env.channel_id),
        (old) => old?.map((m) => (m.id === msg.id ? msg : m)) ?? [],
      )
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

  // Subscribe/unsubscribe loop when channel changes OR connection state changes
  // - On disconnect: reset the ref so we re-subscribe after reconnection
  // - On (re)connect: subscribe to the current channel fresh
  // - On channel switch while connected: unsub old, sub new
  useEffect(() => {
    if (!isConnected) {
      // Connection dropped (or not yet open). Forget what we "think" we're
      // subscribed to so the next connect will re-subscribe cleanly.
      subscribedRef.current = null
      return
    }

    const prev = subscribedRef.current
    const next = activeChannelId
    if (prev === next) return

    try {
      if (prev) {
        send(JSON.stringify({ action: 'unsubscribe', channel_id: prev }))
      }
      if (next) {
        send(JSON.stringify({ action: 'subscribe', channel_id: next }))
      }
      subscribedRef.current = next
    } catch {
      // Socket closed mid-effect (readyState not OPEN). Next isConnected
      // cycle will retry. Don't update the ref.
    }
  }, [isConnected, activeChannelId, send])

  return { isConnected }
}
