<template>
  <div class="bk-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="bk-card-title-group">
          <div class="bk-icon-box bk-icon-blue">
            <FontAwesomeIcon icon="database" />
          </div>
          <div>
            <h3>数据备份与恢复</h3>
            <small>备份系统全部数据，或从备份文件恢复</small>
          </div>
        </div>
      </div>

      <!-- Tab bar -->
      <div class="bk-tab-bar">
        <div class="bk-tab-group">
          <button
            class="bk-tab-btn"
            :class="{ 'bk-tab-active': activeTab === 'backup' }"
            @click="handleTabChange('backup')"
          >
            <FontAwesomeIcon icon="database" /> 备份与恢复
          </button>
          <button
            class="bk-tab-btn"
            :class="{ 'bk-tab-active': activeTab === 'records' }"
            @click="handleTabChange('records')"
          >
            <FontAwesomeIcon icon="history" /> 备份记录
          </button>
        </div>
        <div class="bk-tab-actions">
          <button
            class="bk-action-btn bk-action-secondary"
            :disabled="checking"
            @click="handleIntegrityCheck"
            title="备份完整性巡检"
          >
            <UiLoadingIcon :loading="checking" icon="shield-alt" />
            {{ checking ? '巡检中...' : '完整性巡检' }}
          </button>
        </div>
      </div>

      <!-- Integrity check result -->
      <IntegrityCheckPanel :check-result="checkResult" @close="checkResult = null" />

      <div v-show="activeTab === 'backup'" class="bk-body">
        <!-- 左栏：一键备份 -->
        <div class="bk-col">
          <div class="bk-col-title"><FontAwesomeIcon icon="download" /> 一键备份</div>
          <BackupModeSelector
            :tables="tables"
            :tables-loading="tablesLoading"
            :backup-mode="backupMode"
            :backup-remark="backupRemark"
            :exporting="exporting"
            :saving-to-server="savingToServer"
            :saving-incremental="savingIncremental"
            :save-result="saveResult"
            @update:backup-remark="backupRemark = $event"
            @mode-change="handleModeChange"
            @export="handleExport"
            @save-to-server="handleSaveToServer"
            @save-incremental="handleSaveIncremental"
          />
        </div>

        <!-- 右栏 -->
        <div class="bk-col">
          <!-- 自定义路径模式：文件上传恢复 -->
          <template v-if="backupMode === 'custom'">
            <div class="bk-col-title"><FontAwesomeIcon icon="upload" /> 一键恢复</div>
            <FileRestorePanel
              :selected-file="selectedFile"
              :validation-result="validationResult"
              :importing="importing"
              :restore-result="restoreResult"
              :restore-task-id="restoreTaskId"
              :missing-tables="missingTables"
              @file-select="setFile"
              @file-clear="clearFile"
              @restore="handleRestore"
              @restore-completed="onRestoreProgressCompleted"
              @restore-failed="onRestoreProgressFailed"
            />
          </template>

          <!-- 默认路径模式：服务器备份列表 -->
          <template v-if="backupMode === 'default'">
            <div class="bk-col-title"><FontAwesomeIcon icon="folder-open" /> 服务器备份</div>
            <div class="bk-col-content">
              <!-- 服务器恢复进度条 -->
              <RestoreProgressBar
                v-if="restoreTaskId && backupMode === 'default'"
                :task-id="restoreTaskId"
                @completed="onRestoreProgressCompleted"
                @failed="onRestoreProgressFailed"
              />

              <div v-if="serverBackupsLoading" class="bk-loading-inline"><UiSpinner /></div>

              <div v-else-if="!serverBackups.length" class="bk-empty-state">
                <FontAwesomeIcon icon="inbox" />
                <p>暂无服务器备份</p>
                <small>点击左侧「备份到服务器」创建第一个备份</small>
              </div>

              <div v-else class="bk-backup-list">
                <div v-for="b in serverBackups" :key="b.filename" class="bk-backup-item">
                  <div class="bk-backup-header">
                    <div class="bk-backup-name">
                      <FontAwesomeIcon icon="file-archive" />
                      <span>{{ b.filename }}</span>
                    </div>
                    <div class="bk-backup-actions">
                      <button class="bk-icon-btn bk-icon-btn-primary" :disabled="restoringFile === b.filename" @click="handleServerRestore(b.filename)" title="恢复">
                        <UiLoadingIcon :loading="restoringFile === b.filename" icon="undo-alt" />
                      </button>
                      <button class="bk-icon-btn bk-icon-btn-danger" :disabled="deletingFile === b.filename" @click="handleServerDelete(b.filename)" title="删除">
                        <UiLoadingIcon :loading="deletingFile === b.filename" icon="trash-alt" />
                      </button>
                    </div>
                  </div>
                  <div class="bk-backup-meta">
                    <span v-if="b.format" class="bk-backup-format">
                      <FontAwesomeIcon :icon="b.format === 'incremental' ? 'fas fa-layer-group' : b.format === 'zip' ? 'fas fa-file-archive' : b.format === 'encrypted' ? 'lock' : 'file-code'" />
                      {{ b.format === 'incremental' ? '增量' : b.format === 'zip' ? 'ZIP' : b.format === 'encrypted' ? '加密' : 'JSON' }}
                    </span>
                    <span v-if="b.exported_at"><FontAwesomeIcon icon="clock" /> {{ b.exported_at }}</span>
                    <span v-if="b.exported_by"><FontAwesomeIcon icon="user" /> {{ b.exported_by }}</span>
                    <span><FontAwesomeIcon icon="table" /> {{ b.table_count }} 表 / {{ b.total_rows }} 条</span>
                    <span><FontAwesomeIcon icon="weight" /> {{ formatSize(b.size) }}</span>
                  </div>
                  <!-- ZIP-specific includes badges -->
                  <div v-if="b.format === 'zip' && b.includes" class="bk-backup-includes">
                    <span v-if="b.includes.filestore_count" class="bk-badge"><FontAwesomeIcon icon="paperclip" /> {{ b.includes.filestore_count }} 附件</span>
                    <span v-if="b.includes.config_files?.length" class="bk-badge"><FontAwesomeIcon icon="cog" /> {{ b.includes.config_files.length }} 配置</span>
                    <span v-if="b.includes.redis_rdb" class="bk-badge"><FontAwesomeIcon icon="bolt" /> Redis</span>
                  </div>
                  <!-- Incremental backup: base timestamp -->
                  <div v-if="b.format === 'incremental' && b.base_timestamp" class="bk-backup-includes">
                    <span class="bk-badge bk-badge-inc"><FontAwesomeIcon icon="clock" /> 基于 {{ b.base_timestamp }}</span>
                  </div>
                  <div v-if="b.remark" class="bk-backup-remark">
                    <FontAwesomeIcon icon="comment" /> {{ b.remark }}
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Records tab -->
      <div v-show="activeTab === 'records'" class="bk-records-body">
        <div class="bk-records-content">
          <BackupRecordList
            :records="records"
            :total="recordsTotal"
            :page="recordsPage"
            :page-size="recordsPageSize"
            :loading="recordsLoading"
            @page-change="loadRecords"
          />
        </div>
      </div>
    </div>

    <!-- 确认恢复弹窗 -->
    <UiDialog v-model:open="showConfirmDialog" title="确认恢复数据" max-width-class="max-w-[480px]">
      <template #title-icon><FontAwesomeIcon icon="exclamation-triangle" style="color: var(--color-danger-500);" /></template>
      <div class="bk-confirm-body">
        <div class="bk-confirm-icon"><FontAwesomeIcon icon="exclamation-triangle" /></div>
        <div class="bk-confirm-text">
          <p><b>此操作将清除当前所有数据，并从备份文件恢复。</b></p>
          <p>该操作不可撤销，请确保已做好必要准备。</p>
          <p v-if="confirmTarget">{{ confirmTarget }}</p>
        </div>
      </div>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="showConfirmDialog = false">取消</UiButton>
        <UiButton variant="danger" size="sm" :disabled="importing || !!restoringFile" @click="confirmRestoreAction">
          <UiLoadingIcon :loading="importing || !!restoringFile" icon="undo-alt" />
          {{ restorePhase || (importing || restoringFile ? '恢复中...' : '确认恢复') }}
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { backupApi } from '@/api'
import type { ApiResponse, BackupRecord } from '@/types'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import RestoreProgressBar from '@/components/backup/RestoreProgressBar.vue'
import BackupRecordList from '@/components/backup/BackupRecordList.vue'
import BackupModeSelector from '@/components/backup/BackupModeSelector.vue'
import FileRestorePanel from '@/components/backup/FileRestorePanel.vue'
import IntegrityCheckPanel from '@/components/backup/IntegrityCheckPanel.vue'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

interface BackupSaveResult {
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

// --- Tables overview ---
const queryClient = useQueryClient()
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
const exporting = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    await backupApi.exportBackup(backupRemark.value)
    showToast('备份文件已下载', 'success')
  } catch (e: unknown) {
    showToast(getErrorMessage(e, '备份失败'), 'error')
  } finally {
    exporting.value = false
  }
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
const validationResult = ref<any>(null)
const importing = ref(false)
const restoreResult = ref<any>(null)
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
    if (res.success) validationResult.value = res.summary
  } catch (e: unknown) {
    showToast(getErrorMessage(e, '验证失败'), 'error')
  }
}

const missingTables = computed(() => {
  if (!validationResult.value?.tables) return []
  return validationResult.value.tables.filter((t: any) => !t.exists).map((t: any) => t.name)
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
const serverBackups = ref<any[]>([])
const serverBackupsLoading = ref(false)
const restoringFile = ref('')
const deletingFile = ref('')

async function loadServerBackups() {
  serverBackupsLoading.value = true
  try {
    const res = await backupApi.listServerBackups()
    if (res.success) serverBackups.value = res.backups ?? []
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

function onRestoreProgressCompleted(result: any) {
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
    restoreResult.value = res
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

// --- Utility ---
function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// --- Backup Records ---
const activeTab = ref<'backup' | 'records'>('backup')
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
const checkResult = ref<any>(null)

async function handleIntegrityCheck() {
  checking.value = true
  checkResult.value = null
  try {
    const res = await backupApi.integrityCheck() as ApiResponse & { failed?: number }
    checkResult.value = res
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

function handleTabChange(tab: 'backup' | 'records') {
  activeTab.value = tab
  if (tab === 'records' && !records.value.length) {
    loadRecords()
  }
}
</script>

<style scoped>
/* === Layout === */
.bk-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Header === */
.bk-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.bk-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.bk-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* === Icon Box === */
.bk-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.bk-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* === Body (Two columns) === */
.bk-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* === Column === */
.bk-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.bk-col + .bk-col {
  border-left: 1px solid var(--color-border-light);
}

.bk-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.bk-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.bk-col-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}

/* === Tab Bar === */
.bk-tab-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.bk-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.bk-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.bk-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.bk-tab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2);
  transform: translateY(-1px);
}

.bk-tab-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* === Action Buttons (for integrity check button in tab bar) === */
.bk-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px 18px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-button);
  background: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}

.bk-action-secondary {
  background: var(--color-neutral-100);
  color: var(--color-neutral-700);
  border: 1px solid var(--color-border-light);
  margin-top: 8px;
}

.bk-action-secondary:hover:not(:disabled) {
  background: var(--color-neutral-200);
}

.bk-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

/* === Records Body === */
.bk-records-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.bk-records-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}

/* === Server Backup List === */
.bk-backup-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bk-backup-item {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  padding: 14px 16px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  background: white;
}

.bk-backup-item:hover {
  border-color: var(--color-primary-200);
  box-shadow: var(--shadow-sm);
  transform: translateX(4px);
}

.bk-backup-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.bk-backup-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.bk-backup-name i {
  color: var(--color-primary-500);
  font-size: 14px;
}

.bk-backup-actions {
  display: flex;
  gap: 6px;
}

.bk-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--color-border-light);
  background: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}

.bk-icon-btn-primary {
  color: var(--color-primary-500);
}

.bk-icon-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.bk-icon-btn-danger {
  color: var(--color-danger-500);
}

.bk-icon-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-300);
  transform: translateY(-1px);
}

.bk-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.bk-backup-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.bk-backup-meta i {
  margin-right: 3px;
  font-size: 11px;
  color: var(--color-text-muted);
}

.bk-backup-format {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 8px;
  font-weight: 600;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.bk-backup-remark {
  margin-top: 8px;
  padding: 6px 10px;
  background: var(--color-surface);
  border-radius: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.bk-backup-remark i {
  margin-right: 4px;
  color: var(--color-primary-400);
}

/* === Includes Badges === */
.bk-backup-includes {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.bk-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-weight: 500;
}

.bk-badge-inc {
  background: var(--color-info-50);
  color: var(--color-info-600);
}

/* === Empty State === */
.bk-empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
}

.bk-empty-state i {
  font-size: 36px;
  color: var(--color-border-light);
  margin-bottom: 12px;
  display: block;
}

.bk-empty-state p {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin: 0 0 4px;
}

.bk-empty-state small {
  font-size: 12px;
}

/* === Loading Inline === */
.bk-loading-inline {
  text-align: center;
  padding: 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

/* === Confirm Dialog === */
.bk-confirm-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.bk-confirm-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--color-danger-50);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.bk-confirm-icon i {
  font-size: 22px;
  color: var(--color-danger-500);
}

.bk-confirm-text {
  font-size: 14px;
  color: var(--color-text);
  line-height: 1.6;
}

.bk-confirm-text p {
  margin: 0 0 6px;
}

.bk-confirm-text p:last-child {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
</style>
