/**
 * 统一任务进度轮询（M4）。
 * 备份与还原共用：GET /backup/progress/{task_id}，间隔 800ms，终态即停，404 容忍创建竞态。
 */
import { ref, computed, watch, onScopeDispose, type Ref } from 'vue'
import { backupApi } from '@/api'

export type BackupTaskStatus = 'pending' | 'running' | 'completed' | 'completed_with_warnings' | 'failed'

export interface BackupTaskState {
  taskId: string
  status: BackupTaskStatus | ''
  progress: number
  phase: string
  phaseLabel: string
  error: string | null
  result: unknown
  staleWarning: string | null
}

export interface BackupTaskProgress {
  success?: boolean
  task_id?: string
  status?: string
  progress?: number
  phase?: string
  phase_label?: string
  started_at?: string | null
  completed_at?: string | null
  result?: unknown
  error?: string | null
}

const TERMINAL: ReadonlySet<string> = new Set(['completed', 'completed_with_warnings', 'failed'])
const INTERVAL_MS = 800
/** 任务创建后 Redis 写入存在短暂竞态，404 先容忍再判失败 */
const MAX_NOT_FOUND = 3
/** 超时兜底：超过 60 秒仍停留在 pending/init 时提示 Worker 可能未运行 */
const STALE_TIMEOUT_MS = 60_000

const INITIAL: BackupTaskState = {
  taskId: '',
  status: '',
  progress: 0,
  phase: '',
  phaseLabel: '',
  error: null,
  result: null,
  staleWarning: null,
}

export function useBackupTask(
  taskIdGetter: () => string | null,
  onCompleted?: (result: unknown) => void,
  onFailed?: (error: string) => void,
  enabled: Ref<boolean> | (() => boolean) = () => true,
): {
  state: Ref<BackupTaskState>
  progress: Ref<BackupTaskState>
  status: Ref<BackupTaskStatus | ''>
  error: Ref<string | null>
  result: Ref<unknown>
  staleWarning: Ref<string | null>
} {
  const state = ref<BackupTaskState>({ ...INITIAL })
  let timer: ReturnType<typeof setInterval> | null = null
  let fetching = false
  let notFoundCount = 0
  let finished = false
  let startTime: number | null = null
  let staleWarned = false
  // B6 修复：轮询代数——切换任务后旧任务在途响应一律丢弃，防止旧任务
  // 终态误停新任务轮询并触发错误的 onCompleted/onFailed 回调
  let generation = 0

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  async function pollOnce(taskId: string, gen: number) {
    if (fetching || finished) return
    fetching = true
    try {
      const res = (await backupApi.getProgress(taskId)) as BackupTaskProgress
      // 响应返回时任务已切换（或已重置），丢弃过期响应
      if (gen !== generation) return
      notFoundCount = 0
      const isPendingOrInit =
        (res.status === 'pending' || res.status === undefined) &&
        (!res.phase || res.phase === 'init')
      state.value = {
        taskId,
        status: (res.status as BackupTaskStatus) || 'pending',
        progress: typeof res.progress === 'number' ? res.progress : 0,
        phase: res.phase || '',
        phaseLabel: res.phase_label || '',
        error: res.error || null,
        result: res.result ?? null,
        // 脱离 pending/init 后清除超时提示，终态分支亦会清空
        staleWarning: isPendingOrInit ? state.value.staleWarning : null,
      }
      // 超时兜底：60秒仍停留在 pending/init 时提示 Worker 可能未运行
      if (startTime && !staleWarned) {
        const elapsed = Date.now() - startTime
        const isStale = elapsed > STALE_TIMEOUT_MS
        if (isStale && isPendingOrInit) {
          staleWarned = true
          state.value = {
            ...state.value,
            staleWarning: '备份 Worker 可能未运行（超过60秒仍未开始执行），请检查 erp-arq 服务是否启动',
          }
        }
      }
      if (TERMINAL.has(res.status || '')) {
        finished = true
        stop()
        state.value = { ...state.value, staleWarning: null }
        if (res.status === 'failed') {
          onFailed?.(res.error || '任务失败')
        } else {
          onCompleted?.(res.result ?? null)
        }
      }
    } catch (e) {
      if (gen !== generation) return
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        notFoundCount += 1
        if (notFoundCount >= MAX_NOT_FOUND) {
          finished = true
          stop()
          state.value = { ...state.value, status: 'failed', error: '任务不存在或已过期' }
          onFailed?.('任务不存在或已过期')
        }
      }
      // 其他错误保持当前状态，下一轮继续
    } finally {
      fetching = false
    }
  }

  watch(
    taskIdGetter,
    (taskId) => {
      stop()
      finished = false
      notFoundCount = 0
      generation += 1
      const gen = generation
      const isEnabled = typeof enabled === 'function' ? enabled() : enabled.value
      if (!taskId || !isEnabled) {
        state.value = { ...INITIAL }
        startTime = null
        staleWarned = false
        return
      }
      startTime = Date.now()
      staleWarned = false
      state.value = { ...INITIAL, taskId, status: 'pending', phaseLabel: '等待任务启动…' }
      void pollOnce(taskId, gen)
      timer = setInterval(() => void pollOnce(taskId, gen), INTERVAL_MS)
    },
    { immediate: true },
  )

  onScopeDispose(stop)

  return {
    state,
    progress: state,
    status: computed(() => state.value.status),
    error: computed(() => state.value.error),
    result: computed(() => state.value.result),
    staleWarning: computed(() => state.value.staleWarning),
  }
}