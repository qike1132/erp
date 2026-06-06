// 实时同步模块类型定义

export type SyncStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'error'

export interface WebSocketMessage {
  type: string
  [key: string]: unknown
}

export type SyncEventType =
  | 'stock_changed'
  | 'order_created'
  | 'order_updated'
  | 'order_deleted'
  | 'shipment_completed'
  | 'purchase_order_created'
  | 'product_updated'
  | 'customer_updated'
  | string

export interface SyncConfig {
  wsUrl?: string
  apiBaseUrl?: string
  pollIntervalActive?: number
  pollIntervalInactive?: number
  wsReconnectInterval?: number
  wsMaxReconnectAttempts?: number
  enabledEvents?: SyncEventType[]
  autoStart?: boolean
}

export interface SyncState {
  status: SyncStatus
  lastUpdate: Date | null
  isPageVisible: boolean
  isManualRefresh: boolean
  reconnectAttempts: number
  error: Error | null
}

export interface UseRealTimeSyncOptions {
  config?: Partial<SyncConfig>
  onEvent?: (event: WebSocketMessage) => void
  onRefresh?: () => Promise<void> | void
  onError?: (error: Error) => void
  onStatusChange?: (status: SyncStatus) => void
}

export interface UseRealTimeSyncReturn {
  state: SyncState
  config: SyncConfig
  refresh: () => Promise<void>
  connect: () => void
  disconnect: () => void
  startPolling: () => void
  stopPolling: () => void
  setConfig: (config: Partial<SyncConfig>) => void
  subscribe: (
    eventType: SyncEventType | SyncEventType[],
    callback: (event: WebSocketMessage) => void,
  ) => () => void
}

// 默认配置
export const DEFAULT_SYNC_CONFIG: SyncConfig = {
  pollIntervalActive: 30000, // 30秒
  pollIntervalInactive: 300000, // 5分钟
  wsReconnectInterval: 5000, // 5秒
  wsMaxReconnectAttempts: 20,
  autoStart: true,
  enabledEvents: [
    'stock_changed',
    'order_created',
    'order_updated',
    'order_deleted',
    'shipment_completed',
    'purchase_order_created',
  ],
}
