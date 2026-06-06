# useRealTimeSync 实时同步模块

## 概述

`useRealTimeSync` 是一个功能完整的 Vue 3 composable，用于实现实时数据同步。它结合了 WebSocket 实时推送和智能轮询降级，同时支持 Capacitor 移动应用环境。

## 功能特性

- ✅ **WebSocket 实时推送** - 低延迟的实时数据同步
- ✅ **智能轮询降级** - WebSocket 不可用时自动切换到轮询
- ✅ **自动重连** - 断线后自动重连，支持指数退避
- ✅ **页面可见性感知** - 页面隐藏时降低更新频率
- ✅ **Capacitor 支持** - 完美适配移动应用环境
- ✅ **事件订阅** - 支持订阅特定类型的事件
- ✅ **状态管理** - 完整的同步状态跟踪
- ✅ **错误处理** - 完善的错误处理和重试机制

## 快速开始

### 基础用法

```vue
<script setup lang="ts">
import { useRealTimeSync } from '@/composables/useRealTimeSync'
import SyncStatusIndicator from '@/components/SyncStatusIndicator.vue'

const loadData = async () => {
  // 加载数据的逻辑
  console.log('刷新数据...')
}

const sync = useRealTimeSync({
  onRefresh: loadData,
  onEvent: (event) => {
    console.log('收到事件:', event)
  },
})
</script>

<template>
  <div>
    <SyncStatusIndicator :state="sync.state" />
    <button @click="sync.refresh">手动刷新</button>
  </div>
</template>
```

## API 参考

### UseRealTimeSyncOptions

配置选项：

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `config` | `Partial<SyncConfig>` | - | 同步配置 |
| `onRefresh` | `() => Promise<void> \| void` | - | 数据刷新回调 |
| `onEvent` | `(event: WebSocketMessage) => void` | - | 收到事件回调 |
| `onError` | `(error: Error) => void` | - | 错误回调 |
| `onStatusChange` | `(status: SyncStatus) => void` | - | 状态变化回调 |

### SyncConfig

配置项：

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `wsUrl` | `string` | 自动生成 | WebSocket 地址 |
| `pollIntervalActive` | `number` | `30000` | 活跃时轮询间隔 (ms) |
| `pollIntervalInactive` | `number` | `300000` | 不活跃时轮询间隔 (ms) |
| `wsReconnectInterval` | `number` | `5000` | WebSocket 重连间隔 (ms) |
| `wsMaxReconnectAttempts` | `number` | `20` | 最大重连次数 |
| `enabledEvents` | `SyncEventType[]` | 全部 | 启用的事件类型 |
| `autoStart` | `boolean` | `true` | 是否自动启动 |

### UseRealTimeSyncReturn

返回值：

| 属性/方法 | 类型 | 说明 |
|-----------|------|------|
| `state` | `SyncState` | 同步状态 |
| `config` | `SyncConfig` | 当前配置（响应式） |
| `refresh` | `() => Promise<void>` | 手动刷新数据 |
| `connect` | `() => void` | 连接 WebSocket |
| `disconnect` | `() => void` | 断开 WebSocket |
| `startPolling` | `() => void` | 启动轮询 |
| `stopPolling` | `() => void` | 停止轮询 |
| `setConfig` | `(config: Partial<SyncConfig>) => void` | 更新配置 |
| `subscribe` | `(eventType, callback) => () => void` | 订阅事件 |

### SyncState

状态对象：

| 属性 | 类型 | 说明 |
|------|------|------|
| `status` | `SyncStatus` | 当前状态 |
| `lastUpdate` | `Date \| null` | 最后更新时间 |
| `isPageVisible` | `boolean` | 页面是否可见 |
| `isManualRefresh` | `boolean` | 是否正在手动刷新 |
| `reconnectAttempts` | `number` | 重连尝试次数 |
| `error` | `Error \| null` | 错误信息 |

### SyncStatus

状态枚举：

| 值 | 说明 |
|----|------|
| `idle` | 就绪 |
| `connecting` | 连接中 |
| `connected` | 已连接，实时同步中 |
| `reconnecting` | 重连中 |
| `disconnected` | 已断开 |
| `error` | 错误 |

## 高级用法

### 订阅特定事件

```typescript
const sync = useRealTimeSync({
  onRefresh: loadData,
})

// 订阅单个事件
const unsubscribeStock = sync.subscribe('stock_changed', (event) => {
  console.log('库存变化:', event)
})

// 订阅多个事件
const unsubscribeOrder = sync.subscribe(
  ['order_created', 'order_updated'],
  (event) => {
    console.log('订单变化:', event)
  }
)

// 取消订阅
onUnmounted(() => {
  unsubscribeStock()
  unsubscribeOrder()
})
```

### 自定义配置

```typescript
const sync = useRealTimeSync({
  config: {
    wsUrl: 'ws://custom-host/ws',
    pollIntervalActive: 15000, // 15秒
    pollIntervalInactive: 60000, // 1分钟
    enabledEvents: ['stock_changed', 'order_created'], // 只订阅这两类事件
  },
  onRefresh: loadData,
})

// 动态更新配置
sync.setConfig({
  pollIntervalActive: 10000,
})
```

### 手动控制同步

```typescript
const sync = useRealTimeSync({
  config: {
    autoStart: false, // 不自动启动
  },
  onRefresh: loadData,
})

// 手动启动
const startSync = () => {
  sync.connect()
  sync.startPolling()
}

// 手动停止
const stopSync = () => {
  sync.disconnect()
  sync.stopPolling()
}
```

### 完整状态处理

```typescript
const sync = useRealTimeSync({
  onRefresh: loadData,
  onStatusChange: (status) => {
    switch (status) {
      case 'connected':
        console.log('实时同步已连接')
        break
      case 'reconnecting':
        console.log(`正在重连 (${sync.state.reconnectAttempts}/20)`)
        break
      case 'error':
        console.error('同步出错:', sync.state.error)
        break
    }
  },
  onError: (error) => {
    // 错误处理
    showToast('同步失败，请检查网络')
  },
})
```

## 事件类型

支持的事件类型（可扩展）：

- `stock_changed` - 库存变化
- `order_created` - 订单创建
- `order_updated` - 订单更新
- `order_deleted` - 订单删除
- `shipment_completed` - 发货完成
- `purchase_order_created` - 采购订单创建
- `product_updated` - 产品更新
- `customer_updated` - 客户更新

## UI 组件

### SyncStatusIndicator

同步状态指示器组件：

```vue
<template>
  <SyncStatusIndicator :state="sync.state" />
  <!-- 只显示圆点，不显示文字 -->
  <SyncStatusIndicator :state="sync.state" :show-text="false" />
</template>
```

## 注意事项

1. **组件卸载时自动清理** - composable 会在 `onUnmounted` 时自动清理资源
2. **页面可见性** - 页面隐藏时自动降低更新频率，节省资源
3. **WebSocket 优先** - 优先使用 WebSocket，不可用时自动降级到轮询
4. **Capacitor 支持** - 自动检测移动应用环境，使用对应的配置
5. **错误重试** - 网络错误时自动重试，使用指数退避策略

## 与现有代码集成

项目中已有部分实时同步代码，新模块完全兼容并可以逐步替换：

- `useWebSocket` - 可以迁移到新的 `useRealTimeSync`
- `useAutoRefresh` - 功能已包含在新模块中



## 技术选型参考

### 为什么混合使用 WebSocket + 轮询？

| 方案 | 优点 | 缺点 |
|------|------|------|
| **WebSocket** | 低延迟、实时性好 | 实现复杂、断线问题、端口限制 |
| **轮询** | 简单可靠、兼容性好 | 延迟高、资源浪费 |
| **混合方案** | 兼顾实时性和可靠性 | 实现稍复杂 |

### 参考大厂实践

- **阿里巴巴** - 使用 WebSocket + 降级轮询
- **腾讯** - 长连接 + 心跳保活
- **字节跳动** - WebSocket + 智能断线重连
