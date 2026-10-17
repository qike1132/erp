import { get, post, put, del, upload, download } from './request'
import type { ApiResponse } from '@/types'

/** 备份保存到服务器的响应（顶层字段，与后端 /backup/save 对齐） */
export interface BackupSaveResult {
  success: boolean
  format: string
  filename: string
  size: number
  table_count: number
  total_rows: number
  exported_at?: string
  exported_by?: string
  includes?: {
    filestore_count?: number
    config_files?: string[]
    redis_rdb?: boolean
  }
  remark?: string
}

/** 定时任务项（与后端 BackupSchedule 对齐） */
export interface BackupScheduleItem {
  id?: number | null
  name: string
  task?: string
  task_type?: string | null
  cron_expr?: string | null
  schedule: string
  enabled: boolean
  last_run?: string | null
  last_status?: string | null
}

/** 备份系统设置（单行） */
export interface BackupSettings {
  success?: boolean
  backup_dir: string
  default_backup_dir?: string
  retention_days: number
  max_count: number
  encryption_mode: string
  initialized?: boolean
  updated_by?: string | null
  updated_at?: string | null
  /** 实际生效配置来源：env（表内值仅记录，不生效） */
  effective_source?: string
  /** 实际生效的备份目录（环境变量 BACKUP_DIR） */
  effective_backup_dir?: string
}

/** 路径预检结果 */
export interface BackupPathValidate {
  valid: boolean
  path?: string
  message?: string
  error?: string
}

/** 还原差异预览（第 2 步数据源） */
export interface BackupRestorePlanItem {
  table: string
  backup_rows: number | null
  current_rows: number | null
  diff: number | null
}
export interface BackupRestorePlan {
  success: boolean
  filename?: string
  table_count?: number
  total_backup_rows?: number
  affected_count?: number
  affected_tables?: { table: string; diff: number }[]
  tables?: BackupRestorePlanItem[]
  encrypted?: boolean
  exported_at?: string | null
  error?: string | null
}

/** 还原附加选项（P0-2：敏感配置确认 + 加密包解密密码） */
export interface RestoreOptions {
  confirmSensitive?: boolean
  password?: string
}

/** 分片导出信息（P0-3：bundle_id 命中缓存后各片来自同一份文件） */
export interface BackupChunkInfoDto {
  success: boolean
  filename: string
  total_size: number
  chunk_size: number
  total_chunks: number
  encrypted: boolean
  checksum?: string | null
  bundle_id?: string | null
  created_at: string
}

export const backupApi = {
  tables: () => get<{ success: boolean; tables: { name: string; rows: number }[]; total: number }>('/backup/tables'),
  exportBackup: (remark: string, format: string = 'zip') =>
    download('/backup/export', `erp_backup_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.${format === 'zip' ? 'zip' : 'json'}`, { remark, format }),
  validateFile: (formData: FormData) => upload<{ success: boolean; summary: unknown }>('/backup/validate', formData),
  importBackup: (formData: FormData) => {
    return upload('/backup/import?confirm=true', formData)
  },
  saveToServer: (remark: string) => post<BackupSaveResult>(`/backup/save?remark=${encodeURIComponent(remark)}`),
  listServerBackups: () => get<{ success: boolean; backups: { filename: string; size: number; created_at: string }[]; total: number }>('/backup/list'),
  restoreServerBackup: (filename: string, opts?: RestoreOptions) => {
    const q = new URLSearchParams({ confirm: 'true' })
    if (opts?.confirmSensitive) q.set('confirm_sensitive', 'true')
    // H3：密码经 JSON body 传递，不再进 URL（避免进入访问日志/浏览器历史）
    const body = opts?.password ? { password: opts.password } : undefined  // secret-scan:allow 右值为属性读取，非字面凭据
    return post(`/backup/restore-by-name/${encodeURIComponent(filename)}?${q.toString()}`, body)
  },
  downloadByName: (filename: string) => download(`/backup/download/${encodeURIComponent(filename)}`, filename),
  deleteServerBackup: (filename: string) => del(`/backup/delete-by-name/${encodeURIComponent(filename)}`),
  asyncImport: (formData: FormData, opts?: RestoreOptions) => {
    const q = new URLSearchParams({ confirm: 'true' })
    if (opts?.confirmSensitive) q.set('confirm_sensitive', 'true')
    // H3：multipart 上传场景密码经 X-Backup-Password 请求头传递，不进 URL
    const headers = opts?.password ? { 'X-Backup-Password': opts.password } : undefined
    return upload<{ success: boolean; task_id?: string }>(`/backup/async-import?${q.toString()}`, formData, headers)
  },
  asyncRestoreByName: (filename: string, opts?: RestoreOptions) => {
    const q = new URLSearchParams({ confirm: 'true' })
    if (opts?.confirmSensitive) q.set('confirm_sensitive', 'true')
    // H3：密码经 JSON body 传递，不再进 URL（避免进入访问日志/浏览器历史）
    const body = opts?.password ? { password: opts.password } : undefined  // secret-scan:allow 右值为属性读取，非字面凭据
    return post<{ success: boolean; task_id?: string }>(`/backup/async-restore-by-name/${encodeURIComponent(filename)}?${q.toString()}`, body)
  },
  getProgress: (taskId: string) => get(`/backup/progress/${taskId}`),
  integrityCheck: () => post<{ success: boolean } & ApiResponse>('/backup/integrity-check'),
  getRecords: (page: number = 1, pageSize: number = 20) =>
    get<ApiResponse>(`/backup/records?page=${page}&page_size=${pageSize}`),
  // --- M4 六模块新增绑定（任务化 / 调度 / settings / 概览 / 差异预览） ---
  triggerFull: (payload?: { remark?: string; encrypt?: boolean; password?: string; tables?: string[]; exclude_tables?: string[] }) =>
    post<{ success: boolean; task_id: string; task_name: string; message?: string }>('/backup/full', payload ?? {}),
  getStatus: () => get<ApiResponse & { backup_dir?: string; total_backups?: number; last_full_backup?: unknown; disk_usage_percent?: number | null }>('/backup/status'),
  listSchedules: () => get<{ success: boolean; tasks: BackupScheduleItem[] }>('/backup/schedule'),
  createSchedule: (body: { name: string; task_type: string; cron_expr: string; enabled?: boolean }) =>
    post<{ success: boolean; tasks: BackupScheduleItem[] }>('/backup/schedule', body),
  updateSchedule: (id: number, body: { name?: string; task_type?: string; cron_expr?: string; enabled?: boolean }) =>
    put<{ success: boolean; tasks: BackupScheduleItem[] }>(`/backup/schedule/${id}`, body),
  deleteSchedule: (id: number) => del<{ success: boolean }>(`/backup/schedule/${id}`),
  triggerSchedule: (taskName: string) => post<{ success: boolean }>(`/backup/schedule/trigger?task_name=${encodeURIComponent(taskName)}`),
  getSettings: () => get<BackupSettings>('/backup/settings'),
  saveSettings: (body: { backup_dir?: string; retention_days?: number; max_count?: number; encryption_mode?: string }) =>
    post<BackupSettings>('/backup/settings', body),
  validatePath: (path: string) => post<BackupPathValidate>('/backup/settings/validate-path', { path }),
  restorePlan: (filename: string, password?: string) =>
    post<BackupRestorePlan>('/backup/restore/plan', password ? { filename, password } : { filename }),
  // --- 分片导出（P0-3：先取 bundle_id，再逐片下载，各片与整包 checksum 一致） ---
  getExportInfo: (remark: string, encrypt: boolean) =>
    get<BackupChunkInfoDto>(`/backup/export-info?remark=${encodeURIComponent(remark)}&encrypt=${encrypt ? 'true' : 'false'}`),
  getExportChunk: (chunkIndex: number, bundleId?: string | null) =>
    get(`/backup/export-chunk/${chunkIndex}${bundleId ? `?bundle_id=${encodeURIComponent(bundleId)}` : ''}`),
}
