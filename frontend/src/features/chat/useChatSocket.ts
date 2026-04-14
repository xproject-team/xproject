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
import { useEffect, useRef } from 'react'
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
}


export function useChatSocket({ activeChannelId, currentUserId }: UseChatSocketArgs) {
  const qc = useQueryClient()
  const subscribedRef = useRef<string | null>(null)    // last channel we subscribed to

  const token = getToken()
  const url   = token ? `/api/v1/ws/chat?token=${encodeURIComponent(token)}` : null

  // Message handler — dispatches based on server envelope type
  function handleMessage(raw: string) {
    let env: IncomingEnvelope
    try {
      env = JSON.parse(raw)
    } catch {
      return                                           // malformed — ignore
    }

    if (env.type === 'message' && env.message) {
      const msg = env.message

      // Skip if we sent it — usePostMessage already put it in the cache
      if (msg.sender_id === currentUserId) return

      // Prepend to cache (newest-first ordering, same as REST)
      qc.setQueryData<MessageResponse[]>(
        chatKeys.messages(env.channel_id),
        (old) => {
          if (!old) return [msg]
          if (old.some((m) => m.id === msg.id)) return old   // dedupe
          return [msg, ...old]
        },
      )

      // Refresh channel list so unread_count + last_message_at update
      qc.invalidateQueries({ queryKey: chatKeys.channels() })
    }
  }

  const { isConnected, send } = useWebSocket(url, { onMessage: handleMessage })

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
