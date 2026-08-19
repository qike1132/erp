import { ref, watch, onUnmounted, type Ref } from 'vue'
import { backupApi } from '@/api'
import type { RestoreResult } from './useRestorePolling'

export interface RestoreProgressData {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'completed_with_warnings' | 'failed'
  progress: number
  phase: string
  phase_label: string
  restore_type: string
  started_at: string | null
  completed_at: string | null
  result: RestoreResult | null
  error: string | null
}

const INITIAL_PROGRESS: RestoreProgressData = {
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

export function useRestoreProgressPolling(
  taskIdGetter: () => string | null,
  onCompleted: (result: RestoreResult) => void,
  onFailed: (error: string) => void,
): { progress: Ref<RestoreProgressData> } {
  const progress = ref<RestoreProgressData>({ ...INITIAL_PROGRESS })

  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  function stopPolling() {
    if (pollTimer !== null) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  async function poll() {
    const taskId = taskIdGetter()
    if (stopped || !taskId) return
    try {
      const res = await backupApi.getProgress(taskId) as {
        success?: boolean
        task_id?: string
        status?: 'failed' | 'running' | 'pending' | 'completed' | 'completed_with_warnings'
        progress?: number
        phase?: string
        phase_label?: string
        restore_type?: string
        started_at?: string | null
        completed_at?: string | null
        result?: unknown
        error?: string | null
      }
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
          result: (res.result as RestoreResult | null) ?? null,
          error: res.error || null,
        }
        if (res.status === 'completed' || res.status === 'completed_with_warnings') {
          onCompleted(res.result as RestoreResult)
          return
        }
        if (res.status === 'failed') {
          onFailed(res.error || '恢复失败')
          return
        }
      }
    } catch {
      // ignore poll errors
    }
    pollTimer = setTimeout(poll, 800)
  }

  function startPolling() {
    stopPolling()
    if (!taskIdGetter()) return
    poll()
  }

  watch(taskIdGetter, (newId) => {
    if (newId) {
      progress.value = { ...INITIAL_PROGRESS }
      startPolling()
    } else {
      stopPolling()
    }
  }, { immediate: true })

  onUnmounted(() => {
    stopped = true
    stopPolling()
  })

  return { progress }
}