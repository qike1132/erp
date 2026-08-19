import { ref, watch, onScopeDispose, type Ref } from 'vue'
import { backupApi } from '@/api'

/** 数据库恢复子结果 */
export interface RestoreDbResult {
  status?: 'ok' | 'partial' | 'error' | string
  error?: string
  message?: string
  /** 逐条错误明细（后端可能返回字符串数组或单条字符串） */
  errors?: string[] | string
  [key: string]: unknown
}

/** 数据完整性验证报告（L1 行数 / L2 指纹 / L3 抽样） */
export interface RestoreVerification {
  overall_pass?: boolean
  l1_row_count?: {
    summary?: string
    mismatch?: { table: string; expected: number; actual: number }[]
    [key: string]: unknown
  }
  l2_fingerprint?: {
    summary?: string
    tables_checked?: number
    results?: { table: string; match: boolean | null }[]
    [key: string]: unknown
  }
  l3_sampling?: {
    tables_checked?: number
    [key: string]: unknown
  }
  [key: string]: unknown
}

/** 恢复前安全备份 / 回滚子结果 */
export interface RestoreSideEffect {
  success?: boolean
  filename?: string
  error?: string
  [key: string]: unknown
}

/** 恢复完成后的结果摘要（与后端 BackupProgressOut.result 对齐） */
export interface RestoreResult {
  total_inserted?: number
  format?: string
  database?: RestoreDbResult
  errors?: string[]
  warnings?: string[]
  verification?: RestoreVerification
  pre_restore_backup?: RestoreSideEffect
  rollback?: RestoreSideEffect
  results?: {
    database?: RestoreDbResult
    filestore?: { restored?: number; [key: string]: unknown }
    config?: { restored?: unknown[]; [key: string]: unknown }
    warnings?: string[]
    pre_restore_backup?: RestoreSideEffect
    rollback?: RestoreSideEffect
    verification?: RestoreVerification
    [key: string]: unknown
  }
  [key: string]: unknown
}

export type RestoreStatus = 'pending' | 'running' | 'completed' | 'completed_with_warnings' | 'failed'

export interface RestoreProgressState {
  status: RestoreStatus | ''
  progress: number
  phase_label: string
  error: string | null
  result: RestoreResult | null
}

/** 进度接口响应（fastapi_app.schemas.backup.BackupProgressOut） */
interface BackupProgressOut {
  success: boolean
  task_id: string
  status: string
  progress: number
  phase: string
  phase_label: string
  started_at: string | null
  completed_at: string | null
  result: Record<string, unknown> | null
  error: string | null
}

const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['completed', 'completed_with_warnings', 'failed'])
const POLL_INTERVAL_MS = 1500
/** 任务不存在（404）的容忍次数：任务创建与 Redis 写入存在短暂竞态，先重试再判失败 */
const MAX_NOT_FOUND = 3

const INITIAL_STATE: RestoreProgressState = {
  status: '',
  progress: 0,
  phase_label: '',
  error: null,
  result: null,
}

/**
 * 轮询异步恢复任务进度（GET /backup/progress/{task_id}）。
 *
 * @param taskIdGetter 返回当前任务 ID 的 getter；为 null 时停止轮询
 * @param onCompleted 任务进入终态（completed/completed_with_warnings）时回调
 * @param onFailed 任务失败或进度查询持续异常时回调
 */
export function useRestorePolling(
  taskIdGetter: () => string | null,
  onCompleted?: (result: RestoreResult) => void,
  onFailed?: (error: string) => void,
): { progress: Ref<RestoreProgressState> } {
  const progress = ref<RestoreProgressState>({ ...INITIAL_STATE })
  let timer: ReturnType<typeof setInterval> | null = null
  let fetching = false
  let notFoundCount = 0
  let finished = false

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  async function pollOnce(taskId: string) {
    if (fetching || finished) return
    fetching = true
    try {
      const res = (await backupApi.getProgress(taskId)) as BackupProgressOut
      notFoundCount = 0
      progress.value = {
        status: res.status as RestoreProgressState['status'],
        progress: typeof res.progress === 'number' ? res.progress : 0,
        phase_label: res.phase_label || '',
        error: res.error || null,
        result: (res.result as RestoreResult | null) ?? null,
      }
      if (TERMINAL_STATUSES.has(res.status)) {
        finished = true
        stop()
        if (res.status === 'failed') {
          onFailed?.(res.error || '恢复失败')
        } else {
          onCompleted?.(progress.value.result ?? {})
        }
      }
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        // 任务不存在或已过期：少量重试容忍创建竞态，超出则判失败
        notFoundCount += 1
        if (notFoundCount >= MAX_NOT_FOUND) {
          finished = true
          stop()
          progress.value = { ...progress.value, status: 'failed', error: '恢复任务不存在或已过期' }
          onFailed?.('恢复任务不存在或已过期')
        }
      }
      // 其他网络/5xx 错误：保持当前状态，下一轮继续轮询（axios 层已有重试）
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
      if (!taskId) {
        progress.value = { ...INITIAL_STATE }
        return
      }
      progress.value = { ...INITIAL_STATE, status: 'pending', phase_label: '等待任务启动…' }
      void pollOnce(taskId)
      timer = setInterval(() => void pollOnce(taskId), POLL_INTERVAL_MS)
    },
    { immediate: true },
  )

  onScopeDispose(stop)

  return { progress }
}
