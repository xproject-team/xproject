/**
 * WebSocket hook with automatic reconnection (exponential backoff).
 *
 * Only retries if the connection was successfully established at least
 * once. If the very first connect fails, we give up — prevents infinite
 * reconnect loops when the URL / backend is broken.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: string) => void
  reconnectDelay?: number
}

export function useWebSocket(url: string | null, options: UseWebSocketOptions = {}) {
  const { onMessage, reconnectDelay = 1000 } = options

  const ws               = useRef<WebSocket | null>(null)
  const everConnected    = useRef(false)
  const retryTimer       = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stopped          = useRef(false)
  const [isConnected, setIsConnected] = useState(false)
  const delay            = useRef(reconnectDelay)

  const connect = useCallback(() => {
    if (!url || stopped.current) return

    let socket: WebSocket
    try {
      socket = new WebSocket(url)
    } catch {
      // Constructor itself failed — do not retry
      stopped.current = true
      return
    }

    ws.current = socket

    socket.onopen = () => {
      everConnected.current = true
      setIsConnected(true)
      delay.current = reconnectDelay
    }

    socket.onmessage = (e) => onMessage?.(e.data)

    socket.onerror = () => {
      // If we never established the connection, stop trying.
      // Browsers emit onerror + onclose in rapid succession when
      // an upgrade handshake fails (e.g. bad token) — without this
      // guard we'd loop forever.
      if (!everConnected.current) stopped.current = true
    }

    socket.onclose = () => {
      setIsConnected(false)
      if (stopped.current) return
      if (!everConnected.current) return   // never opened → don't retry

      // Reconnect with exponential backoff (capped at 30s)
      const next = Math.min(delay.current * 2, 30_000)
      delay.current = next
      retryTimer.current = setTimeout(connect, next)
    }
  }, [url, onMessage, reconnectDelay])

  useEffect(() => {
    // Reset stop flag whenever the URL changes
    stopped.current     = false
    everConnected.current = false
    delay.current       = reconnectDelay
    connect()

    return () => {
      stopped.current = true
      if (retryTimer.current) clearTimeout(retryTimer.current)
      ws.current?.close()
    }
  }, [connect, reconnectDelay])

  const send = useCallback((data: string) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(data)
    }
  }, [])

  return { isConnected, send }
}
