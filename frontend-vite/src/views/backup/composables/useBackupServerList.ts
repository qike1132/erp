/**
 * useBackupServerList — 服务器备份列表域（批次 2-3 拆分自 useBackupCenter）
 *
 * 承载服务器备份列表加载与删除。逻辑原样搬移。
 */
import { ref } from 'vue'
import { backupApi } from '@/api'
import type { ApiResponse } from '@/types'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

// 服务器备份条目
export interface ServerBackupItem {
  filename: string
  size: number
  format?: string
  exported_at?: string
  exported_by?: string
  table_count?: number
  total_rows?: number
  remark?: string
  base_timestamp?: string
  includes?: { filestore_count?: number; config_files?: string[]; redis_rdb?: boolean }
}

export function useBackupServerList() {
  const serverBackups = ref<ServerBackupItem[]>([])
  const serverBackupsLoading = ref(false)
  const deletingFile = ref('')

  async function loadServerBackups() {
    serverBackupsLoading.value = true
    try {
      const res = await backupApi.listServerBackups()
      if (res.success) serverBackups.value = (res.backups ?? []) as ServerBackupItem[]
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '加载服务器备份列表失败'), 'error')
    } finally {
      serverBackupsLoading.value = false
    }
  }

  async function handleServerDelete(filename: string) {
    deletingFile.value = filename
    try {
      const res = await backupApi.deleteServerBackup(filename) as ApiResponse
      if (res.success) {
        showToast('备份已删除', 'success')
        serverBackups.value = serverBackups.value.filter(b => b.filename !== filename)
      }
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除失败'), 'error')
    } finally {
      deletingFile.value = ''
    }
  }

  return {
    serverBackups,
    serverBackupsLoading,
    deletingFile,
    loadServerBackups,
    handleServerDelete,
  }
}
