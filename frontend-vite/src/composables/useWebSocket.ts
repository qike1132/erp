import { onMounted, onUnmounted } from 'vue'
import type { Ref } from 'vue'
import { websocketApi } from '@/api/auth'

interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

interface UseWebSocketOptions {
  onMessage: (data: WebSocketMessage) => void
  isActive: Ref<boolean>
  maxReconnectAttempts?: number
  reconnectBaseDelay?: number
}

const HEARTBEAT_INTERVAL_MS = 30_000

export function useWebSocket(options: UseWebSocketOptions) {
  const { onMessage, isActive, maxReconnectAttempts = 20, reconnectBaseDelay = 3000 } = options

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let reconnectAttempts = 0
  let manuallyClosed = false
  let connecting = false

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  function sendPing() {
    if (ws?.readyState === WebSocket.OPEN) ws.send('ping')
  }

  async function connect() {
    if (manuallyClosed || connecting || reconnectAttempts >= maxReconnectAttempts) return
    connecting = true

    try {
      const { ticket } = await websocketApi.ticket()

      if (manuallyClosed) return

      // Web 环境使用一次性票据握手；Cookie 仍由后端兼容支持。
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws/notifications`
      const socket = new WebSocket(wsUrl)
      ws = socket

      socket.onopen = () => {
        if (ws !== socket) return
        reconnectAttempts = 0
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: 'auth', token: ticket }))
        }
        stopHeartbeat()
        heartbeatTimer = setInterval(sendPing, HEARTBEAT_INTERVAL_MS)
      }

      socket.onmessage = (event) => {
        if (ws !== socket || !isActive.value) return
        if (event.data === 'pong') return
        try {
          const data: WebSocketMessage = JSON.parse(event.data)
          onMessage(data)
        } catch {
          /* ignore non-JSON messages */
        }
      }

      socket.onclose = () => {
        if (ws !== socket) return
        stopHeartbeat()
        ws = null
        if (manuallyClosed) return
        reconnectAttempts++
        if (reconnectAttempts < maxReconnectAttempts) {
          const delay = Math.min(reconnectBaseDelay * reconnectAttempts, 30000)
          reconnectTimer = setTimeout(connect, delay)
        }
      }

      socket.onerror = () => {
        socket.close()
      }
    } catch {
      if (manuallyClosed) return
      reconnectAttempts++
      if (reconnectAttempts < maxReconnectAttempts) {
        const delay = Math.min(reconnectBaseDelay * reconnectAttempts, 30000)
        reconnectTimer = setTimeout(connect, delay)
      }
    } finally {
      connecting = false
    }
  }

  function cleanup() {
    manuallyClosed = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    stopHeartbeat()
    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.close()
      ws = null
    }
  }

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    cleanup()
  })

  return { cleanup }
}
