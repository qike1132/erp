<template>
  <div class="rp-container">
    <RestoreProgressHeader
      :status-title="statusTitle"
      :phase-label="progress.phase_label"
      :display-percent="displayPercent"
      :icon-class="iconClass"
      :icon-name="iconName"
      :percent-class="percentClass"
    />

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

    <RestoreProgressResult
      v-if="isCompleted && progress.result"
      :result="progress.result"
      :has-db-error="hasDbError"
      :result-summary-class="resultSummaryClass"
      :result-icon="resultIcon"
      :result-text="resultText"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import RestoreProgressHeader from './components/RestoreProgressHeader.vue'
import RestoreProgressResult from './components/RestoreProgressResult.vue'
import { useRestoreProgressPolling, type RestoreProgressData } from './composables/useRestoreProgressPolling'
import type { RestoreResult } from './composables/useRestorePolling'

export type { RestoreResult }
export type { RestoreProgressData }

const props = defineProps<{
  taskId: string | null
}>()

const emit = defineEmits<{
  (e: 'completed', result: RestoreResult): void
  (e: 'failed', error: string): void
}>()

const { progress } = useRestoreProgressPolling(
  () => props.taskId,
  (result) => emit('completed', result),
  (error) => emit('failed', error),
)

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
</script>

<style scoped>
.rp-container {
  padding: 16px;
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), var(--color-surface, #fff));
  border: 1px solid var(--color-primary-200, #bfdbfe);
  border-radius: 12px;
  margin-bottom: 16px;
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
</style>
