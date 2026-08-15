// 备份中心全部业务逻辑：表信息 / 备份导出 / 服务器备份 / 文件恢复 / 增量备份 / 备份记录 / 完整性巡检
// （从 BackupView.vue 抽出，行为不变；顺带将原 6 处 any 收敛为显式接口）
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { backupApi } from '@/api'
import type { ApiResponse, BackupRecord } from '@/types'
import { showToast } from '@/composables/useToast'
import { useExport } from '@/composables/useExport'
import { getErrorMessage } from '@/types/errors'
import type { IntegrityCheckResult } from '@/components/backup/IntegrityCheckPanel.vue'

// 备份文件校验摘要（/backup/validate 返回 summary）
export interface BackupValidateSummary {
  table_count?: number
  total_rows?: number
  tables?: { name: string; exists: boolean }[]
}

// 恢复结果汇总（含 ZIP 完整备份的分组结果）
export interface RestoreSummary {
  format?: string
  total_inserted?: number
  errors?: unknown[]
  database?: { status?: string; error?: string; message?: string }
  verification?: {
    overall_pass?: boolean
    l1_row_count?: { summary?: string }
    l2_fingerprint?: { summary?: string }
  }
  results?: {
    database?: { status?: string; error?: string; message?: string }
    verification?: { overall_pass?: boolean; l1_row_count?: { summary?: string }; l2_fingerprint?: { summary?: string } }
    warnings?: unknown[]
  }
}

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

// 备份保存结果（保存到服务器 / 增量备份）
export interface BackupSaveResult {
  filename: string
  size: number
  format: string
  table_count: number
  total_rows: number
  includes?: {
    filestore_count?: number
    config_files?: string[]
    redis_rdb?: boolean
  }
}

export function useBackupCenter() {
  const queryClient = useQueryClient()

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

  // --- Backup mode ---
  const backupMode = ref<'custom' | 'default'>('custom')
  const backupRemark = ref('')

  function handleModeChange(mode: 'custom' | 'default') {
    backupMode.value = mode
    if (mode === 'default') loadServerBackups()
  }

  // --- Custom path: export (download) ---
  const { exporting, runExport } = useExport({ start: false, success: '备份文件已下载', error: '备份失败' })

  function handleExport() {
    runExport(() => backupApi.exportBackup(backupRemark.value))
  }

  // --- Default path: save to server ---
  const savingToServer = ref(false)
  const saveResult = ref<BackupSaveResult | null>(null)

  async function handleSaveToServer() {
    savingToServer.value = true
    saveResult.value = null
    try {
      const res = await backupApi.saveToServer(backupRemark.value)
      if (res.success) {
        saveResult.value = res
        showToast('备份已保存到服务器', 'success')
        loadServerBackups()
        loadTables()
      }
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '保存到服务器失败'), 'error')
    } finally {
      savingToServer.value = false
    }
  }

  // --- Custom path: file upload & restore ---
  const selectedFile = ref<File | null>(null)
  const validationResult = ref<BackupValidateSummary | null>(null)
  const importing = ref(false)
  const restoreResult = ref<RestoreSummary | null>(null)
  const restorePhase = ref('')
  const restoreTaskId = ref<string | null>(null)

  function setFile(file: File) {
    const allowed = ['.json', '.zip', '.gz']
    if (!allowed.some(ext => file.name.toLowerCase().endsWith(ext))) {
      showToast('请选择 .zip / .json / .gz 备份文件', 'warning')
      return
    }
    selectedFile.value = file
    validationResult.value = null
    restoreResult.value = null
    validateFile(file)
  }

  function clearFile() {
    selectedFile.value = null
    validationResult.value = null
    restoreResult.value = null
  }

  async function validateFile(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await backupApi.validateFile(formData)
      if (res.success) validationResult.value = res.summary as BackupValidateSummary
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '验证失败'), 'error')
    }
  }

  const missingTables = computed(() => {
    if (!validationResult.value?.tables) return []
    return validationResult.value.tables.filter((t) => !t.exists).map((t) => t.name)
  })

  function handleRestore() {
    if (!selectedFile.value) {
      showToast('请先选择备份文件', 'warning')
      return
    }
    pendingRestoreAction = 'file'
    confirmTarget.value = `将恢复 ${validationResult.value?.table_count || '?'} 个数据表、${validationResult.value?.total_rows || '?'} 条记录。`
    showConfirmDialog.value = true
  }

  // --- Default path: server backup list ---
  const serverBackups = ref<ServerBackupItem[]>([])
  const serverBackupsLoading = ref(false)
  const restoringFile = ref('')
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

  function handleServerRestore(filename: string) {
    const backup = serverBackups.value.find(b => b.filename === filename)
    const isIncremental = backup?.format === 'incremental'
    pendingRestoreAction = isIncremental ? 'incremental' : 'server'
    pendingRestoreFilename = filename
    if (isIncremental) {
      confirmTarget.value = `将增量恢复「${filename}」的数据（UPSERT 模式，不删除现有数据）。`
    } else {
      confirmTarget.value = `将从「${filename}」恢复 ${backup?.table_count || '?'} 个数据表、${backup?.total_rows || '?'} 条记录。`
    }
    showConfirmDialog.value = true
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

  // --- Confirm dialog ---
  const showConfirmDialog = ref(false)
  const confirmTarget = ref('')
  let pendingRestoreAction: 'file' | 'server' | 'incremental' | null = null
  let pendingRestoreFilename = ''

  async function confirmRestoreAction() {
    if (pendingRestoreAction === 'file') {
      await doFileRestore()
    } else if (pendingRestoreAction === 'server') {
      await doServerRestore()
    } else if (pendingRestoreAction === 'incremental') {
      await doIncrementalRestore()
    }
    showConfirmDialog.value = false
    pendingRestoreAction = null
  }

  async function doFileRestore() {
    if (!selectedFile.value) return
    importing.value = true
    restorePhase.value = '正在启动恢复任务...'
    restoreResult.value = null
    restoreTaskId.value = null
    try {
      const formData = new FormData()
      formData.append('file', selectedFile.value)
      const res = await backupApi.asyncImport(formData)
      if (res.success && res.task_id) {
        restoreTaskId.value = res.task_id
        restorePhase.value = '恢复任务已启动，请等待完成...'
      } else {
        restorePhase.value = ''
        importing.value = false
        showToast('启动恢复任务失败', 'error')
      }
    } catch (e: unknown) {
      restorePhase.value = ''
      importing.value = false
      showToast(getErrorMessage(e, '启动恢复失败'), 'error')
    }
  }

  function onRestoreProgressCompleted(result: RestoreSummary | null) {
    importing.value = false
    restoringFile.value = ''
    restorePhase.value = ''
    restoreResult.value = result
    if (result) {
      const dbStatus = result.database?.status || result.results?.database?.status || ''
      const dbFailed = dbStatus === 'error'
      const dbPartial = dbStatus === 'partial'
      const verificationOk = (result.verification || result.results?.verification)?.overall_pass !== false
      const verificationFailed = !verificationOk

      if (dbFailed) {
        const errMsg = result.database?.error || result.database?.message || result.results?.database?.error || result.results?.database?.message || '数据库恢复失败'
        showToast(`恢复失败: ${errMsg}`, 'error')
      } else if (verificationFailed) {
        const l1Summary = (result.verification || result.results?.verification)?.l1_row_count?.summary || ''
        const l2Summary = (result.verification || result.results?.verification)?.l2_fingerprint?.summary || ''
        showToast(`恢复完成但验证未通过: ${l1Summary}${l2Summary ? '; ' + l2Summary : ''}`, 'warning')
      } else if (dbPartial) {
        showToast(`恢复完成，但有部分语句执行失败`, 'warning')
      } else {
        const isZip = result.format === 'zip' || result.results?.database
        const msg = isZip
          ? `恢复成功（完整备份${result.total_inserted ? '，共 ' + result.total_inserted + ' 条记录' : ''}）`
          : `恢复成功，共 ${result.total_inserted ?? 0} 条记录`
        const hasErrors = result.errors?.length || result.results?.warnings?.length
        showToast(msg, hasErrors ? 'warning' : 'success')
      }
      queryClient.invalidateQueries()
      loadTables()
    }
  }

  function onRestoreProgressFailed(error: string) {
    importing.value = false
    restoringFile.value = ''
    restorePhase.value = ''
    showToast(error || '恢复失败', 'error')
  }

  async function doServerRestore() {
    if (!pendingRestoreFilename) return
    restoringFile.value = pendingRestoreFilename
    restorePhase.value = '正在启动恢复任务...'
    restoreResult.value = null
    restoreTaskId.value = null
    try {
      const res = await backupApi.asyncRestoreByName(pendingRestoreFilename)
      if (res.success && res.task_id) {
        restoreTaskId.value = res.task_id
        restorePhase.value = '恢复任务已启动，请等待完成...'
      } else {
        restorePhase.value = ''
        restoringFile.value = ''
        showToast('启动恢复任务失败', 'error')
      }
    } catch (e: unknown) {
      restorePhase.value = ''
      restoringFile.value = ''
      showToast(getErrorMessage(e, '启动恢复失败'), 'error')
    }
  }

  // --- Incremental backup ---
  const savingIncremental = ref(false)

  async function handleSaveIncremental() {
    savingIncremental.value = true
    try {
      const res = await backupApi.saveIncremental(backupRemark.value)
      if (res.success) {
        showToast(`增量备份成功: ${res.filename} (${res.total_rows} 条变更)`, 'success')
        loadServerBackups()
        loadTables()
      }
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '增量备份失败'), 'error')
    } finally {
      savingIncremental.value = false
    }
  }

  async function doIncrementalRestore() {
    if (!pendingRestoreFilename) return
    restoringFile.value = pendingRestoreFilename
    restorePhase.value = '正在增量恢复数据...'
    try {
      const res = await backupApi.restoreIncremental(pendingRestoreFilename)
      restoreResult.value = res as RestoreSummary
      if (res.success) {
        const msg = `增量恢复成功，共更新 ${res.total_upserted || 0} 条记录`
        showToast(msg, 'success')
        queryClient.invalidateQueries()
        loadTables()
        loadServerBackups()
      }
    } catch (e: unknown) {
      restorePhase.value = ''
      showToast(getErrorMessage(e, '增量恢复失败'), 'error')
    } finally {
      restorePhase.value = ''
      restoringFile.value = ''
      pendingRestoreFilename = ''
    }
  }

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
    // 表信息
    tables, tablesLoading,
    // 备份模式与导出
    backupMode, backupRemark, handleModeChange, exporting, handleExport,
    // 保存到服务器 / 增量备份
    savingToServer, saveResult, handleSaveToServer, savingIncremental, handleSaveIncremental,
    // 文件恢复
    selectedFile, validationResult, importing, restoreResult, restorePhase, restoreTaskId,
    setFile, clearFile, missingTables, handleRestore,
    // 服务器备份
    serverBackups, serverBackupsLoading, restoringFile, deletingFile,
    loadServerBackups, handleServerRestore, handleServerDelete,
    // 确认弹窗与恢复流程
    showConfirmDialog, confirmTarget, confirmRestoreAction,
    onRestoreProgressCompleted, onRestoreProgressFailed,
    // 备份记录
    records, recordsTotal, recordsPage, recordsPageSize, recordsLoading, loadRecords,
    // 完整性巡检
    checking, checkResult, handleIntegrityCheck,
  }
}
