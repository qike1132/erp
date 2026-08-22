<template>
  <div class="ba-card">
    <div class="ba-actions">
      <button class="ba-btn ba-btn-primary" :disabled="busy || !!task?.taskId" @click="onFull">
        一键全量备份
      </button>
      <button class="ba-btn ba-btn-outline" :disabled="busy || !!task?.taskId" @click="onIncremental">
        增量备份
      </button>
      <span v-if="busy" class="ba-mutex-hint">有任务执行中</span>
    </div>

    <div v-if="task?.taskId" class="ba-task">
      <div class="ba-task-head">
        <span class="ba-badge" :class="statusClass">{{ statusLabel }}</span>
        <span class="ba-task-title">{{ taskTitle }}</span>
      </div>
      <div class="ba-progress-row">
        <div class="ba-progress">
          <div class="ba-progress-fill" :class="task.status === 'failed' ? 'ba-fill-danger' : 'ba-fill-processing'" :style="{ width: pct + '%' }"></div>
        </div>
        <span class="ba-pct">{{ pct }}%</span>
      </div>
      <div class="ba-task-meta">
        <span class="ba-stage">{{ task.phaseLabel || task.phase }}</span>
        <span v-if="task.error" class="ba-error">{{ task.error }}</span>
      </div>
    </div>
    <div v-else-if="noTaskHint" class="ba-hint">{{ noTaskHint }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BackupTaskState, BackupTaskStatus } from './composables/useBackupTask'

const props = defineProps<{
  busy: boolean
  task: BackupTaskState | null
  onFull: () => void
  onIncremental: () => void
  noTaskHint?: string
}>()

const pct = computed(() => Math.round(props.task?.progress ?? 0))
const statusLabel = computed(() => {
  const s: BackupTaskStatus | '' = props.task?.status ?? ''
  if (s === 'completed' || s === 'completed_with_warnings') return '已完成'
  if (s === 'failed') return '失败'
  if (s === 'running' || s === 'pending') return '进行中'
  return ''
})
const statusClass = computed(() => {
  const s = props.task?.status
  if (s === 'failed') return 'ba-badge-danger'
  if (s === 'completed' || s === 'completed_with_warnings') return 'ba-badge-success'
  return 'ba-badge-processing'
})
const taskTitle = computed(() => {
  const s = props.task?.status
  if (s === 'completed' || s === 'completed_with_warnings') return '备份 · 已完成'
  if (s === 'failed') return '备份 · 失败'
  return '备份 · 执行中'
})
</script>

<style scoped>
.ba-card { border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; background: var(--color-surface, #fff); padding: 20px; }
.ba-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.ba-btn { height: 40px; padding: 0 24px; border-radius: 8px; border: 1px solid transparent; font-size: 15px; font-weight: 500; cursor: pointer; }
.ba-btn:disabled { background: var(--color-surface-muted, #f2f3f5); color: var(--color-text-disabled, #c9cdd4); cursor: not-allowed; }
.ba-btn-primary { background: var(--color-primary, #2f7bff); color: #fff; }
.ba-btn-primary:hover:not(:disabled) { background: #1f66e6; }
.ba-btn-outline { background: var(--color-surface, #fff); border-color: var(--color-border-strong, #c9cdd4); color: var(--color-primary, #2f7bff); }
.ba-btn-outline:hover:not(:disabled) { background: #e6f0ff; }
.ba-mutex-hint { font-size: 12px; color: var(--color-text-tertiary, #86909c); }
.ba-task { margin-top: 16px; border: 1px solid var(--color-border, #e5e6eb); border-radius: 8px; padding: 16px; }
.ba-task-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ba-badge { padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; }
.ba-badge-processing { background: #e9eafe; color: #4338ca; }
.ba-badge-success { background: #e6faf1; color: #047857; }
.ba-badge-danger { background: #ffece8; color: #b91c1c; }
.ba-task-title { font-size: 14px; font-weight: 500; }
.ba-progress-row { display: flex; align-items: center; gap: 12px; }
.ba-progress { flex: 1; height: 8px; background: var(--color-surface-muted, #f2f3f5); border-radius: 999px; overflow: hidden; }
.ba-progress-fill { height: 100%; border-radius: 999px; transition: width .2s ease; }
.ba-fill-processing { background: #6366f1; }
.ba-fill-danger { background: var(--color-danger, #ef4444); }
.ba-pct { min-width: 44px; text-align: right; font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 500; }
.ba-task-meta { margin-top: 8px; display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.ba-stage { font-size: 13px; color: var(--color-text-secondary, #4e5969); }
.ba-error { font-size: 13px; color: var(--color-danger, #ef4444); }
.ba-hint { margin-top: 12px; font-size: 13px; color: var(--color-text-tertiary, #86909c); }
</style>