import { get, post, del, upload, download } from './request'
import type { ApiResponse } from '@/types'

export const backupApi = {
  tables: () => get<ApiResponse<{ name: string; rows: number }[]>>('/backup/tables'),
  exportBackup: (remark: string, format: string = 'zip') =>
    download('/backup/export', `erp_backup_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.${format === 'zip' ? 'zip' : 'json'}`, { remark, format }),
  validateFile: (formData: FormData) => upload<ApiResponse>('/backup/validate', formData),
  importBackup: (formData: FormData) => {
    return upload('/backup/import?confirm=true', formData)
  },
  saveToServer: (remark: string) => post<ApiResponse>(`/backup/save?remark=${encodeURIComponent(remark)}`),
  listServerBackups: () => get<ApiResponse<{ filename: string; size: number; created_at: string }[]>>('/backup/list'),
  restoreServerBackup: (filename: string) => post(`/backup/restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  deleteServerBackup: (filename: string) => del(`/backup/delete-by-name/${encodeURIComponent(filename)}`),
  saveIncremental: (remark: string, since?: string) =>
    post(`/backup/save-incremental?remark=${encodeURIComponent(remark)}${since ? '&since=' + encodeURIComponent(since) : ''}`),
  restoreIncremental: (filename: string) =>
    post(`/backup/restore-incremental/${encodeURIComponent(filename)}?confirm=true`),
  asyncImport: (formData: FormData) => upload<ApiResponse>('/backup/async-import?confirm=true', formData),
  asyncRestoreByName: (filename: string) => post<ApiResponse>(`/backup/async-restore-by-name/${encodeURIComponent(filename)}?confirm=true`),
  getProgress: (taskId: string) => get(`/backup/progress/${taskId}`),
  integrityCheck: () => post<ApiResponse>('/backup/integrity-check'),
  getRecords: (page: number = 1, pageSize: number = 20) =>
    get<ApiResponse>(`/backup/records?page=${page}&page_size=${pageSize}`),
  getSchedule: () => get<ApiResponse>('/backup/schedule'),
  triggerSchedule: (taskName: string) => post<ApiResponse>(`/backup/schedule/trigger?task_name=${encodeURIComponent(taskName)}`),
  getStatus: () => get<ApiResponse>('/backup/status'),
}
