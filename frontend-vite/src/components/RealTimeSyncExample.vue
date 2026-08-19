<template>
  <div class="real-time-sync-example">
    <h3>实时同步示例</h3>
    
    <div class="example-section">
      <h4>同步状态</h4>
      <SyncStatusIndicator :state="sync.state" />
      <div v-if="sync.state.lastUpdate" class="last-update">
        最后更新: {{ formatDate(sync.state.lastUpdate) }}
      </div>
    </div>

    <div class="example-section">
      <h4>数据展示</h4>
      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="error" class="error">加载失败: {{ error }}</div>
      <div v-else class="data-container">
        <div class="data-item">
          <span class="data-label">订单数量:</span>
          <span class="data-value">{{ data.orders?.length || 0 }}</span>
        </div>
        <div class="data-item">
          <span class="data-label">库存变化:</span>
          <span class="data-value">{{ stockChanges }}</span>
        </div>
      </div>
    </div>

    <div class="example-section">
      <h4>操作</h4>
      <div class="button-group">
        <button @click="sync.refresh" :disabled="sync.state.isManualRefresh" class="btn" :aria-label="sync.state.isManualRefresh ? '刷新中...' : '手动刷新'">
          {{ sync.state.isManualRefresh ? '刷新中...' : '手动刷新' }}
        </button>
        <button @click="sync.connect" :disabled="sync.state.status === 'connected'" class="btn" aria-label="连接">
          连接
        </button>
        <button @click="sync.disconnect" :disabled="sync.state.status === 'disconnected'" class="btn btn--danger" aria-label="断开">
          断开
        </button>
      </div>
    </div>

    <div class="example-section">
      <h4>事件日志</h4>
      <div class="event-log">
        <div v-for="(event, index) in eventLog" :key="index" class="event-item">
          <span class="event-time">{{ formatTime(event.time) }}</span>
          <span class="event-type">{{ event.type }}</span>
          <span class="event-data">{{ JSON.stringify(event.data) }}</span>
        </div>
        <div v-if="eventLog.length === 0" class="event-empty">暂无事件</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRealTimeSync } from '@/composables/useRealTimeSync'
import SyncStatusIndicator from './SyncStatusIndicator.vue'
import { get } from '@/api/request'
import { devLog } from '@/utils/devLog'

interface Order {
  id: string
  order_no: string
  total: number
}

interface DashboardData {
  orders?: Order[]
}

const data = ref<DashboardData>({})
const loading = ref(false)
const error = ref<string | null>(null)
const eventLog = ref<{ time: Date; type: string; data: unknown }[]>([])
const stockChanges = ref(0)

const loadData = async () => {
  loading.value = true
  error.value = null
  try {
    // 示例 API 调用 - 根据实际情况调整
    const result = await get<Order[]>('/orders')
    data.value = { orders: result }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

const sync = useRealTimeSync({
  onRefresh: loadData,
  onEvent: (event) => {
    eventLog.value.unshift({
      time: new Date(),
      type: event.type,
      data: event,
    })
    // 只保留最近 20 条
    if (eventLog.value.length > 20) {
      eventLog.value.pop()
    }
  },
  onError: (err) => {
    console.error('同步错误:', err)
  },
  onStatusChange: (status) => {
    devLog('同步状态变化:', status)
  },
})

// 订阅特定事件
const unsubscribeStock = sync.subscribe('stock_changed', (event) => {
  stockChanges.value++
  devLog('库存变化:', event)
})

const unsubscribeOrder = sync.subscribe(['order_created', 'order_updated'], (event) => {
  devLog('订单变化:', event)
})

const formatDate = (date: Date) => {
  return date.toLocaleString('zh-CN')
}

const formatTime = (date: Date) => {
  return date.toLocaleTimeString('zh-CN')
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
  unsubscribeStock()
  unsubscribeOrder()
})
</script>

<style scoped>
.real-time-sync-example {
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
}

.example-section {
  margin-bottom: 24px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
}

.example-section h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: #374151;
}

.last-update {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}

.loading,
.error {
  padding: 16px;
  text-align: center;
  border-radius: 4px;
}

.loading {
  background: #f3f4f6;
}

.error {
  background: #fef2f2;
  color: #dc2626;
}

.data-container {
  display: flex;
  gap: 24px;
}

.data-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.data-label {
  font-size: 12px;
  color: #6b7280;
}

.data-value {
  font-size: 24px;
  font-weight: 600;
  color: #111827;
}

.button-group {
  display: flex;
  gap: 8px;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  background: #3b82f6;
  color: white;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn:hover:not(:disabled) {
  background: #2563eb;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--danger {
  background: #ef4444;
}

.btn--danger:hover:not(:disabled) {
  background: #dc2626;
}

.event-log {
  max-height: 200px;
  overflow-y: auto;
  background: white;
  border-radius: 4px;
  padding: 8px;
}

.event-item {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  border-bottom: 1px solid #f3f4f6;
}

.event-item:last-child {
  border-bottom: none;
}

.event-time {
  color: #9ca3af;
  min-width: 70px;
}

.event-type {
  color: #3b82f6;
  font-weight: 500;
  min-width: 120px;
}

.event-data {
  color: #6b7280;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-empty {
  padding: 16px;
  text-align: center;
  color: #9ca3af;
  font-size: 14px;
}
</style>
