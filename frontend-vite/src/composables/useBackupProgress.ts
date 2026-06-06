/**
 * 备份/恢复进度追踪 composable
 *
 * 封装轮询逻辑，支持备份和恢复两种模式。
 * 默认 1000ms 轮询，关键阶段可缩短到 500ms。
 */
import { ref, computed, watch } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { backupApi } from '@/api'

export interface ProgressData {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'completed_with_warnings' | 'failed'
  progress: number
  phase: string
  phase_label: string
  started_at: string | null
  completed_at: string | null
  result: Record<string, unknown> | null
  error: string | null
}

export function useBackupProgress() {
  const progress = ref<ProgressData | null>(null)
  const isPolling = ref(false)
  let currentTaskId: string | null = null

  const displayPercent = computed(() => {
    if (!progress.value) return 0
    const p = Math.round(progress.value.progress)
    return Math.min(100, Math.max(0, p))
  })

  const isRunning = computed(() =>
    progress.value?.status === 'running' || progress.value?.status === 'pending',
  )

  const isCompleted = computed(() =>
    progress.value?.status === 'completed' || progress.value?.status === 'completed_with_warnings',
  )

  const isFailed = computed(() => progress.value?.status === 'failed')

  const statusTitle = computed(() => {
    switch (progress.value?.status) {
      case 'pending': return '准备中...'
      case 'running': return '处理中...'
      case 'completed': return '完成'
      case 'completed_with_warnings': return '完成（有警告）'
      case 'failed': return '失败'
      default: return ''
    }
  })

  async function fetchProgress(taskId: string) {
    try {
      const res = await backupApi.getProgress(taskId) as Record<string, unknown>
      if (res.success) {
        progress.value = {
          task_id: res.task_id as string,
          status: res.status as ProgressData['status'],
          progress: res.progress as number,
          phase: res.phase as string,
          phase_label: res.phase_label as string,
          started_at: res.started_at as string | null,
          completed_at: res.completed_at as string | null,
          result: res.result as Record<string, unknown> | null,
          error: res.error as string | null,
        }

        if (progress.value.status === 'completed' || progress.value.status === 'completed_with_warnings' || progress.value.status === 'failed') {
          stopPolling()
        }
      }
    } catch {
      // 404 means task expired or doesn't exist
      stopPolling()
    }
  }

  const { pause: pausePoll, resume: resumePoll, isActive: isIntervalActive } = useIntervalFn(
    () => { if (currentTaskId) fetchProgress(currentTaskId) },
    1000,
    { immediate: false, controls: true },
  )

  function startPolling(taskId: string, intervalMs: number = 1000) {
    stopPolling()
    currentTaskId = taskId
    isPolling.value = true
    progress.value = {
      task_id: taskId,
      status: 'pending',
      progress: 0,
      phase: 'init',
      phase_label: '初始化',
      started_at: null,
      completed_at: null,
      result: null,
      error: null,
    }

    fetchProgress(taskId)
    resumePoll()
  }

  function stopPolling() {
    pausePoll()
    isPolling.value = false
    currentTaskId = null
  }

  function reset() {
    stopPolling()
    progress.value = null
  }

  return {
    progress,
    isPolling,
    displayPercent,
    isRunning,
    isCompleted,
    isFailed,
    statusTitle,
    startPolling,
    stopPolling,
    reset,
  }
}
