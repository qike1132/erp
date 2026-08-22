/**
 * 恢复任务类型定义（M4 清理：死函数 useRestorePolling 已移除，仅保留被外部引用的类型）。
 * 恢复进度轮询改由 useRestoreProgressPolling 统一承担。
 */

/** 数据库恢复子结果 */
export interface RestoreDbResult {
  status?: 'ok' | 'partial' | 'error' | string
  error?: string
  message?: string
  /** 逐条错误明细（后端可能返回字符串数组或单条字符串） */
  errors?: string[] | string
  [key: string]: unknown
}

/** 数据完整性验证报告（L1 行数 / L2 指纹 / L3 抽样 / L4 表结构） */
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
  l4_schema?: {
    tables_checked?: number
    mismatch?: unknown[]
    note?: string
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