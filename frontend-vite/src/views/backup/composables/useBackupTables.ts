/**
 * useBackupTables — 备份中心只读视图域（批次 2-3 拆分自 useBackupCenter）
 *
 * 承载表信息加载、备份记录分页、完整性巡检。逻辑原样搬移。
 */
import { ref } from 'vue'
import { backupApi } from '@/api'
import type { ApiResponse, BackupRecord } from '@/types'
import { showToast } from '@/composables/useToast'
import type { IntegrityCheckResult } from '@/components/backup/IntegrityCheckPanel.vue'

export function useBackupTables() {
  // --- Tables overview ---
  const tables = ref<{ name: string; rows: number }[]>([])
  const tablesLoading = ref(false)

  async function loadTables() {
    tablesLoading.value = true
    try {
      const res = await backupApi.tables()
      if (res.success) tables.value = res.tables ?? []
    } catch {
      showToast('加载表信息失败', 'error')
    } finally {
      tablesLoading.value = false
    }
  }
  loadTables()

  // --- Backup Records ---
  const records = ref<BackupRecord[]>([])
  const recordsTotal = ref(0)
  const recordsPage = ref(1)
  const recordsPageSize = 20
  const recordsLoading = ref(false)

  async function loadRecords(page: number = 1) {
    recordsLoading.value = true
    try {
      const res = await backupApi.getRecords(page, recordsPageSize) as ApiResponse & { records?: BackupRecord[]; total?: number }
      if (res.success) {
        records.value = res.records ?? []
        recordsTotal.value = res.total ?? 0
        recordsPage.value = page
      }
    } catch {
      showToast('加载备份记录失败', 'error')
    } finally {
      recordsLoading.value = false
    }
  }

  // --- Integrity Check ---
  const checking = ref(false)
  const checkResult = ref<IntegrityCheckResult | null>(null)

  async function handleIntegrityCheck() {
    checking.value = true
    checkResult.value = null
    try {
      const res = await backupApi.integrityCheck() as ApiResponse & { failed?: number; passed?: number; latest_backup?: string; latest_backup_size?: number }
      checkResult.value = res as IntegrityCheckResult
      if (res.failed === 0) {
        showToast('备份完整性巡检通过', 'success')
      } else {
        showToast(`巡检发现 ${res.failed} 个问题`, 'warning')
      }
    } catch {
      showToast('完整性巡检失败', 'error')
    } finally {
      checking.value = false
    }
  }

  return {
    tables,
    tablesLoading,
    loadTables,
    records,
    recordsTotal,
    recordsPage,
    recordsPageSize,
    recordsLoading,
    loadRecords,
    checking,
    checkResult,
    handleIntegrityCheck,
  }
}
