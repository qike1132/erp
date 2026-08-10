<template>
  <div class="rp-container">
    <div class="rp-header">
      <div class="rp-header-left">
        <div class="rp-icon" :class="iconClass">
          <i :class="iconName" />
        </div>
        <div class="rp-header-text">
          <div class="rp-title">{{ statusTitle }}</div>
          <div v-if="progress.phase_label" class="rp-phase">{{ progress.phase_label }}</div>
        </div>
      </div>
      <div class="rp-percent" :class="percentClass">{{ displayPercent }}%</div>
    </div>

    <div class="rp-bar-track">
      <div
        class="rp-bar-fill"
        :class="barClass"
        :style="{ width: `${displayPercent}%` }"
      />
      <div v-if="isRunning" class="rp-bar-shimmer" />
    </div>

    <div v-if="progress.error" class="rp-error">
      <FontAwesomeIcon icon="exclamation-circle" /> {{ progress.error }}
    </div>

    <div v-if="isCompleted && progress.result" class="rp-result-summary" :class="resultSummaryClass">
      <i :class="resultIcon" />
      {{ resultText }}
      <span v-if="progress.result.total_inserted && !hasDbError"> · {{ progress.result.total_inserted }} 条记录</span>
      <span v-if="(progress.result.format === 'zip' || progress.result.database) && !hasDbError"> · ZIP完整备份</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { backupApi } from '@/api'

export interface RestoreProgressData {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'completed_with_warnings' | 'failed'
  progress: number
  phase: string
  phase_label: string
  restore_type: string
  started_at: string | null
  completed_at: string | null
  result: any | null
  error: string | null
}

const props = defineProps<{
  taskId: string | null
}>()

const emit = defineEmits<{
  (e: 'completed', result: any): void
  (e: 'failed', error: string): void
}>()

const progress = ref<RestoreProgressData>({
  task_id: '',
  status: 'pending',
  progress: 0,
  phase: 'init',
  phase_label: '初始化',
  restore_type: '',
  started_at: null,
  completed_at: null,
  result: null,
  error: null,
})

const displayPercent = computed(() => {
  const p = Math.round(progress.value.progress)
  return Math.min(100, Math.max(0, p))
})

const isRunning = computed(() =>
  progress.value.status === 'running' || progress.value.status === 'pending',
)

const isCompleted = computed(() => progress.value.status === 'completed' || progress.value.status === 'completed_with_warnings')

const isFailed = computed(() => progress.value.status === 'failed')

const hasWarnings = computed(() => progress.value.status === 'completed_with_warnings')

const statusTitle = computed(() => {
  switch (progress.value.status) {
    case 'pending': return '准备恢复...'
    case 'running': return '恢复中...'
    case 'completed': return '恢复完成'
    case 'completed_with_warnings': return '恢复完成（验证未通过）'
    case 'failed': return '恢复失败'
    default: return ''
  }
})

const iconClass = computed(() => ({
  'rp-icon-pending': progress.value.status === 'pending',
  'rp-icon-running': progress.value.status === 'running',
  'rp-icon-completed': progress.value.status === 'completed',
  'rp-icon-warning': progress.value.status === 'completed_with_warnings',
  'rp-icon-failed': progress.value.status === 'failed',
}))

const iconName = computed(() => {
  switch (progress.value.status) {
    case 'pending': return 'fas fa-hourglass-half'
    case 'running': return 'fas fa-spinner fa-spin'
    case 'completed': return 'fas fa-check-circle'
    case 'completed_with_warnings': return 'fas fa-exclamation-triangle'
    case 'failed': return 'fas fa-times-circle'
    default: return 'fas fa-database'
  }
})

const barClass = computed(() => ({
  'rp-bar-primary': isRunning.value,
  'rp-bar-success': progress.value.status === 'completed',
  'rp-bar-warning': progress.value.status === 'completed_with_warnings',
  'rp-bar-danger': isFailed.value,
}))

const percentClass = computed(() => ({
  'rp-percent-primary': isRunning.value || progress.value.status === 'pending',
  'rp-percent-success': progress.value.status === 'completed',
  'rp-percent-warning': progress.value.status === 'completed_with_warnings',
  'rp-percent-danger': isFailed.value,
}))

const hasDbError = computed(() => {
  const dbStatus = progress.value.result?.database?.status || progress.value.result?.results?.database?.status
  return dbStatus === 'error'
})

const resultSummaryClass = computed(() => {
  if (hasDbError.value) return 'rp-result-failed'
  if (hasWarnings.value) return 'rp-result-warning'
  return ''
})

const resultIcon = computed(() => {
  if (hasDbError.value) return 'fas fa-exclamation-circle'
  if (hasWarnings.value) return 'fas fa-exclamation-triangle'
  return 'fas fa-check-circle'
})

const resultText = computed(() => {
  if (hasDbError.value) return '恢复失败（已自动回滚）'
  if (hasWarnings.value) return '恢复完成（验证未通过）'
  return '恢复完成'
})

let pollTimer: ReturnType<typeof setTimeout> | null = null
let stopped = false

function startPolling() {
  stopPolling()
  if (!props.taskId) return
  poll()
}

async function poll() {
  if (stopped || !props.taskId) return
  try {
    const res = await backupApi.getProgress(props.taskId) as any
    if (res?.success) {
      progress.value = {
        task_id: res.task_id || '',
        status: res.status || 'pending',
        progress: res.progress ?? 0,
        phase: res.phase || '',
        phase_label: res.phase_label || '',
        restore_type: res.restore_type || '',
        started_at: res.started_at || null,
        completed_at: res.completed_at || null,
        result: res.result || null,
        error: res.error || null,
      }
      if (res.status === 'completed' || res.status === 'completed_with_warnings') {
        emit('completed', res.result)
        return
      }
      if (res.status === 'failed') {
        emit('failed', res.error || '恢复失败')
        return
      }
    }
  } catch {
    // ignore poll errors
  }
  pollTimer = setTimeout(poll, 800)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

watch(() => props.taskId, (newId) => {
  if (newId) {
    progress.value = {
      task_id: '',
      status: 'pending',
      progress: 0,
      phase: 'init',
      phase_label: '初始化',
      restore_type: '',
      started_at: null,
      completed_at: null,
      result: null,
      error: null,
    }
    startPolling()
  } else {
    stopPolling()
  }
}, { immediate: true })

onUnmounted(() => {
  stopped = true
  stopPolling()
})
</script>

<style scoped>
.rp-container {
  padding: 16px;
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), var(--color-surface, #fff));
  border: 1px solid var(--color-primary-200, #bfdbfe);
  border-radius: 12px;
  margin-bottom: 16px;
}

.rp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.rp-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.rp-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.rp-icon-pending {
  background: var(--color-primary-100, #dbeafe);
  color: var(--color-primary-600, #2563eb);
}

.rp-icon-running {
  background: var(--color-primary-100, #dbeafe);
  color: var(--color-primary-600, #2563eb);
}

.rp-icon-completed {
  background: var(--color-success-100, #dcfce7);
  color: var(--color-success-600, #16a34a);
}

.rp-icon-warning {
  background: var(--color-warning-100, #fef9c3);
  color: var(--color-warning-600, #ca8a04);
}

.rp-icon-failed {
  background: var(--color-danger-100, #fee2e2);
  color: var(--color-danger-600, #dc2626);
}

.rp-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
}

.rp-phase {
  font-size: 12px;
  color: var(--color-text-secondary, #64748b);
  margin-top: 2px;
}

.rp-percent {
  font-size: 28px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.rp-percent-primary {
  color: var(--color-primary-600, #2563eb);
}

.rp-percent-success {
  color: var(--color-success-600, #16a34a);
}

.rp-percent-warning {
  color: var(--color-warning-600, #ca8a04);
}

.rp-percent-danger {
  color: var(--color-danger-600, #dc2626);
}

.rp-bar-track {
  width: 100%;
  height: 10px;
  background: var(--color-border-light, #e2e8f0);
  border-radius: 5px;
  overflow: hidden;
  position: relative;
}

.rp-bar-fill {
  height: 100%;
  border-radius: 5px;
  transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  z-index: 1;
}

.rp-bar-primary {
  background: linear-gradient(90deg, var(--color-primary-400, #60a5fa), var(--color-primary-600, #2563eb));
}

.rp-bar-success {
  background: linear-gradient(90deg, var(--color-success-400, #4ade80), var(--color-success-600, #16a34a));
}

.rp-bar-warning {
  background: linear-gradient(90deg, var(--color-warning-400, #facc15), var(--color-warning-600, #ca8a04));
}

.rp-bar-danger {
  background: linear-gradient(90deg, var(--color-danger-400, #f87171), var(--color-danger-600, #dc2626));
}

.rp-bar-shimmer {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.3) 50%,
    transparent 100%
  );
  animation: rp-shimmer 1.8s ease-in-out infinite;
  z-index: 2;
}

@keyframes rp-shimmer {
  0% { left: -100%; }
  100% { left: 100%; }
}

.rp-error {
  margin-top: 10px;
  padding: 8px 12px;
  background: var(--color-danger-50, #fef2f2);
  border-radius: 8px;
  font-size: 12px;
  color: var(--color-danger-600, #dc2626);
}

.rp-result-summary {
  margin-top: 10px;
  padding: 8px 12px;
  background: var(--color-success-50, #f0fdf4);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-success-700, #15803d);
  font-weight: 500;
}

.rp-result-failed {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-700, #b91c1c);
}

.rp-result-warning {
  background: var(--color-warning-50, #fefce8);
  color: var(--color-warning-700, #a16207);
}
</style>
