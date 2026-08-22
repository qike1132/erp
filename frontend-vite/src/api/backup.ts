import { get, post, del, upload, download } from './request'
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
  restoreServerBackup: (filename: string) => post(`/backup/restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  deleteServerBackup: (filename: string) => del(`/backup/delete-by-name/${encodeURIComponent(filename)}`),
  saveIncremental: (remark: string, since?: string) =>
    post<{ success: boolean; filename?: string; total_rows?: number }>(`/backup/save-incremental?remark=${encodeURIComponent(remark)}${since ? '&since=' + encodeURIComponent(since) : ''}`),
  restoreIncremental: (filename: string) =>
    post<{ success: boolean; total_upserted?: number }>(`/backup/restore-incremental/${encodeURIComponent(filename)}?confirm=true`),
  asyncImport: (formData: FormData) => upload<{ success: boolean; task_id?: string }>('/backup/async-import?confirm=true', formData),
  asyncRestoreByName: (filename: string) => post<{ success: boolean; task_id?: string }>(`/backup/async-restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  getProgress: (taskId: string) => get(`/backup/progress/${taskId}`),
  integrityCheck: () => post<{ success: boolean } & ApiResponse>('/backup/integrity-check'),
  getRecords: (page: number = 1, pageSize: number = 20) =>
    get<ApiResponse>(`/backup/records?page=${page}&page_size=${pageSize}`),
}
