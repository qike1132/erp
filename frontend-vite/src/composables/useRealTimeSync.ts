import { reactive, onMounted, onUnmounted } from 'vue'
import {
  DEFAULT_SYNC_CONFIG,
  type SyncConfig,
  type SyncState,
  type SyncStatus,
  type WebSocketMessage,
  type SyncEventType,
  type UseRealTimeSyncOptions,
  type UseRealTimeSyncReturn,
} from '@/types/realtimeSync'

const isCap = !!import.meta.env.VITE_CAPACITOR

function getWsUrl(customUrl?: string): string {
  if (customUrl) return customUrl

  if (isCap) {
    const base = import.meta.env.VITE_WS_BASE_URL as string
    return `${base}/ws/notifications`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/notifications`
}

export function useRealTimeSync(options: UseRealTimeSyncOptions = {}): UseRealTimeSyncReturn {
  const { config: customConfig, onEvent, onRefresh, onError, onStatusChange } = options

  const config = reactive<SyncConfig>({
    ...DEFAULT_SYNC_CONFIG,
    ...customConfig,
  })

  const state = reactive<SyncState>({
    status: 'idle',
    lastUpdate: null,
    isPageVisible: true,
    isManualRefresh: false,
    reconnectAttempts: 0,
    error: null,
  })

  let ws: WebSocket | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let manuallyClosed = false
  let appStateListener: (() => Promise<void>) | null = null

  const subscribers = new Map<SyncEventType, Set<(event: WebSocketMessage) => void>>()

  function setStatus(newStatus: SyncStatus) {
    if (state.status !== newStatus) {
      state.status = newStatus
      onStatusChange?.(newStatus)
    }
  }

  function handleError(error: Error) {
    state.error = error
    setStatus('error')
    onError?.(error)
    console.error('[RealTimeSync] Error:', error)
  }

  function shouldProcessEvent(eventType: string): boolean {
    if (!config.enabledEvents || config.enabledEvents.length === 0) return true
    return config.enabledEvents.includes(eventType as SyncEventType)
  }

  function notifySubscribers(event: WebSocketMessage) {
    const callbacks = subscribers.get(event.type as SyncEventType)
    if (callbacks) {
      callbacks.forEach((cb) => {
        try {
          cb(event)
        } catch (err) {
          console.error('[RealTimeSync] Subscriber error:', err)
        }
      })
    }
    onEvent?.(event)
  }

  async function refresh() {
    if (!onRefresh) return

    state.isManualRefresh = true
    try {
      await onRefresh()
      state.lastUpdate = new Date()
    } catch (err) {
      handleError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      state.isManualRefresh = false
    }
  }

  function connect() {
    if (state.status === 'connected' || state.status === 'connecting') return
    if (state.reconnectAttempts >= (config.wsMaxReconnectAttempts || 20)) {
      setStatus('error')
      return
    }

    manuallyClosed = false
    setStatus('connecting')

    try {
      const wsUrl = getWsUrl(config.wsUrl)
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        state.reconnectAttempts = 0
        state.error = null
        setStatus('connected')
        console.log('[RealTimeSync] WebSocket connected')
      }

      ws.onmessage = (event) => {
        if (!state.isPageVisible) return

        try {
          const data: WebSocketMessage = JSON.parse(event.data)
          
          if (data.type === 'pong') return

          if (shouldProcessEvent(data.type)) {
            notifySubscribers(data)
            
            if (onRefresh) {
              refresh()
            }
          }
        } catch (err) {
          console.warn('[RealTimeSync] Failed to parse message:', err)
        }
      }

      ws.onclose = () => {
        if (manuallyClosed) {
          setStatus('disconnected')
          return
        }

        setStatus('reconnecting')
        state.reconnectAttempts++

        if (state.reconnectAttempts < (config.wsMaxReconnectAttempts || 20)) {
          const delay = Math.min(
            (config.wsReconnectInterval || 5000) * state.reconnectAttempts,
            30000,
          )
          reconnectTimer = setTimeout(connect, delay)
        } else {
          setStatus('error')
        }
      }

      ws.onerror = () => {
        ws?.close()
      }
    } catch (err) {
      handleError(err instanceof Error ? err : new Error(String(err)))
    }
  }

  function disconnect() {
    manuallyClosed = true

    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }

    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.close()
      ws = null
    }

    setStatus('disconnected')
  }

  function startPolling() {
    if (pollTimer) return

    pollTimer = setInterval(async () => {
      if (document.hidden || !state.isPageVisible) return
      if (state.status === 'connected') return

      if (onRefresh) {
        try {
          await refresh()
        } catch {
          // Silent fail
        }
      }
    }, state.isPageVisible ? (config.pollIntervalActive || 30000) : (config.pollIntervalInactive || 300000))
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function setConfig(newConfig: Partial<SyncConfig>) {
    Object.assign(config, newConfig)
  }

  function subscribe(
    eventType: SyncEventType | SyncEventType[],
    callback: (event: WebSocketMessage) => void,
  ): () => void {
    const types = Array.isArray(eventType) ? eventType : [eventType]

    types.forEach((type) => {
      if (!subscribers.has(type)) {
        subscribers.set(type, new Set())
      }
      subscribers.get(type)!.add(callback)
    })

    return () => {
      types.forEach((type) => {
        subscribers.get(type)?.delete(callback)
        if (subscribers.get(type)?.size === 0) {
          subscribers.delete(type)
        }
      })
    }
  }

  function handleVisibilityChange() {
    state.isPageVisible = !document.hidden
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (state.isPageVisible && state.status !== 'connected') {
      startPolling()
    }
    if (state.isPageVisible) {
      if (onRefresh) {
        refresh()
      }
      if (!manuallyClosed && ws?.readyState !== WebSocket.OPEN) {
        state.reconnectAttempts = 0
        connect()
      }
    }
  }

  async function setupAppStateListener() {
    if (!isCap) return

    try {
      const { App } = await import('@capacitor/app')
      const listener = await App.addListener('appStateChange', (stateChange) => {
        state.isPageVisible = stateChange.isActive
        if (stateChange.isActive) {
          if (onRefresh) {
            refresh()
          }
          if (!manuallyClosed && ws?.readyState !== WebSocket.OPEN) {
            state.reconnectAttempts = 0
            connect()
          }
        }
      })
      appStateListener = async () => { await listener.remove() }
    } catch (err) {
      console.warn('[RealTimeSync] Failed to setup app state listener:', err)
    }
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange)
    setupAppStateListener()

    if (config.autoStart) {
      connect()
      startPolling()
    }
  })

  onUnmounted(async () => {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    
    disconnect()
    stopPolling()
    
    subscribers.clear()
    
    if (appStateListener) {
      await appStateListener()
    }
  })

  return {
    state,
    config,
    refresh,
    connect,
    disconnect,
    startPolling,
    stopPolling,
    setConfig,
    subscribe,
  }
}
