import { ref, onMounted, onUnmounted } from 'vue'
import type { Ref } from 'vue'

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

export function useWebSocket(options: UseWebSocketOptions) {
  const { onMessage, isActive, maxReconnectAttempts = 20, reconnectBaseDelay = 3000 } = options

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manuallyClosed = false

  function connect() {
    if (reconnectAttempts >= maxReconnectAttempts) return

    // Web 环境：同源 WS（由 Vite proxy / nginx 反代转发到后端）
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/notifications`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      reconnectAttempts = 0
    }

    ws.onmessage = (event) => {
      if (!isActive.value) return
      try {
        const data: WebSocketMessage = JSON.parse(event.data)
        onMessage(data)
      } catch {
        /* ignore non-JSON messages */
      }
    }

    ws.onclose = () => {
      if (manuallyClosed) return
      reconnectAttempts++
      if (reconnectAttempts < maxReconnectAttempts) {
        const delay = Math.min(reconnectBaseDelay * reconnectAttempts, 30000)
        reconnectTimer = setTimeout(connect, delay)
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function cleanup() {
    manuallyClosed = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
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
