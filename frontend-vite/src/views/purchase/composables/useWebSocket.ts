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

const isCap = !!import.meta.env.VITE_CAPACITOR

export function useWebSocket(options: UseWebSocketOptions) {
  const { onMessage, isActive, maxReconnectAttempts = 20, reconnectBaseDelay = 3000 } = options

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  let manuallyClosed = false

  function connect() {
    if (reconnectAttempts >= maxReconnectAttempts) return

    let wsUrl: string
    if (isCap) {
      const base = import.meta.env.VITE_WS_BASE_URL as string
      wsUrl = `${base}/ws/notifications`
    } else {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      wsUrl = `${protocol}//${window.location.host}/ws/notifications`
    }

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

  let resumeCleanup: (() => Promise<void>) | null = null

  onMounted(async () => {
    connect()
    if (isCap) {
      const { App } = await import('@capacitor/app')
      const listener = await App.addListener('appStateChange', (state) => {
        if (state.isActive && !manuallyClosed && ws?.readyState !== WebSocket.OPEN) {
          reconnectAttempts = 0
          connect()
        }
      })
      resumeCleanup = async () => { await listener.remove() }
    }
  })

  onUnmounted(async () => {
    cleanup()
    if (resumeCleanup) await resumeCleanup()
  })

  return { cleanup }
}
