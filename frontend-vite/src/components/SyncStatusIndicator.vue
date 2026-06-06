<template>
  <div class="sync-status" :class="`sync-status--${state.status}`" :title="statusText">
    <span class="sync-status__dot" :class="`sync-status__dot--${state.status}`"></span>
    <span v-if="showText" class="sync-status__text">{{ statusText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SyncState, SyncStatus } from '@/types/realtimeSync'

interface Props {
  state: SyncState
  showText?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  showText: true,
})

const statusText = computed(() => {
  const statusMap: Record<SyncStatus, string> = {
    idle: '就绪',
    connecting: '连接中...',
    connected: '实时同步中',
    reconnecting: `重连中 (${props.state.reconnectAttempts}/${20})`,
    disconnected: '已断开',
    error: '连接错误',
  }
  return statusMap[props.state.status] || '未知状态'
})
</script>

<style scoped>
.sync-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.sync-status--idle {
  background: rgba(107, 114, 128, 0.1);
  color: #6b7280;
}

.sync-status--connecting {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.sync-status--connected {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.sync-status--reconnecting {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.sync-status--disconnected {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.sync-status--error {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.sync-status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.sync-status__dot--idle {
  background: #6b7280;
}

.sync-status__dot--connecting {
  background: #3b82f6;
  animation: sync-bounce 0.8s ease-in-out infinite;
}

.sync-status__dot--connected {
  background: #22c55e;
  animation: sync-pulse 2s ease-in-out infinite;
}

.sync-status__dot--reconnecting {
  background: #f59e0b;
  animation: sync-bounce 0.5s ease-in-out infinite;
}

.sync-status__dot--disconnected,
.sync-status__dot--error {
  background: #ef4444;
}

@keyframes sync-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(1.2);
  }
}

@keyframes sync-bounce {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.3);
  }
}
</style>
