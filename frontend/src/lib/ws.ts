/**
 * WebSocket hook with automatic reconnection (exponential backoff).
 * One global connection per event — share via useDashboardWS() across components.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: string) => void
  reconnectDelay?: number
}

export function useWebSocket(url: string | null, options: UseWebSocketOptions = {}) {
  const { onMessage, reconnectDelay = 1000 } = options
  const ws = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const delay = useRef(reconnectDelay)

  const connect = useCallback(() => {
    if (!url) return
    const socket = new WebSocket(url)
    ws.current = socket

    socket.onopen = () => {
      setIsConnected(true)
      delay.current = reconnectDelay
    }
    socket.onmessage = (e) => onMessage?.(e.data)
    socket.onclose = () => {
      setIsConnected(false)
      setTimeout(connect, Math.min(delay.current * 2, 30_000))
      delay.current = Math.min(delay.current * 2, 30_000)
    }
  }, [url, onMessage, reconnectDelay])

  useEffect(() => {
    connect()
    return () => ws.current?.close()
  }, [connect])

  const send = useCallback((data: string) => ws.current?.send(data), [])

  return { isConnected, send }
}
