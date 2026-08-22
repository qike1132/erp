<template>
  <div class="bk-center">
    <div class="bk-head">
      <div class="bk-head-title">数据备份中心</div>
      <div class="bk-head-sub">生产环境 · 数据备份与恢复</div>
    </div>

    <section class="bk-section">
      <BackupOverviewCards :status="status" :loading="statusLoading" />
    </section>

    <section class="bk-section">
      <BackupActions
        :busy="busy"
        :task="taskState"
        :on-full="triggerFull"
        :on-incremental="triggerIncremental"
        no-task-hint="选择全量或增量，同一时刻至多执行一个任务"
      />
    </section>

    <section class="bk-section bk-grid-two">
      <ScheduleConfig
        :schedules="schedules"
        :saving="saving"
        :on-save="saveSchedule"
        :on-delete="deleteSchedule"
        :on-trigger="triggerScheduleNow"
      />
      <PathSettings
        :settings="settings"
        :saving="saving"
        :on-validate="validatePath"
        :on-save="savePath"
      />
    </section>

    <section class="bk-section">
      <RestoreWizard
        :open="wizardOpen"
        :server-backups="serverBackups"
        :plan="plan"
        :task="taskState"
        :on-preview="previewPlan"
        :on-execute="executeRestore"
        @close="wizardOpen = false"
      />
      <div class="bk-actions-row">
        <button class="bk-btn-primary" @click="openWizard">一键还原向导</button>
        <label class="bk-btn-outline">
          从文件上传还原
          <input type="file" accept=".zip,.json,.gz" hidden @change="onUploadRestore" />
        </label>
      </div>
      <div v-if="uploadRestoring" class="bk-upload-note">上传文件还原中：{{ (taskState?.phaseLabel) || '处理中…' }}</div>
    </section>

    <section class="bk-section">
      <BackupRecordTable
        :rows="records"
        :total="recordsTotal"
        :page="recordsPage"
        :page-size="recordsPageSize"
        :loading="recordsLoading"
        :on-page-change="loadRecords"
        @restore="onRecordRestore"
        @download="onRecordDownload"
      />
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { backupApi } from '@/api'
import type { BackupRestorePlan, BackupScheduleItem, BackupSettings } from '@/api/backup'
import BackupOverviewCards from '@/components/backup/BackupOverviewCards.vue'
import BackupActions from '@/components/backup/BackupActions.vue'
import ScheduleConfig from '@/components/backup/ScheduleConfig.vue'
import PathSettings from '@/components/backup/PathSettings.vue'
import RestoreWizard, { type ServerBackupSummary } from '@/components/backup/RestoreWizard.vue'
import BackupRecordTable, { type BackupRecordRow } from '@/components/backup/BackupRecordTable.vue'
import { useBackupTask } from '@/components/backup/composables/useBackupTask'

/* ---------- 概览 / 调度 / 设置 ---------- */
const status = ref<Record<string, unknown> | null>(null)
const statusLoading = ref(false)
const schedules = ref<BackupScheduleItem[]>([])
const settings = ref<BackupSettings | null>(null)
const saving = ref(false)

/* ---------- 任务进度（备份 + 还原 + 上传共用统一轮询） ---------- */
const activeTaskId = ref<string | null>(null)
const busy = ref(false)
const { state: taskState } = useBackupTask(
  () => activeTaskId.value,
  () => { busy.value = false },
  () => { busy.value = false },
)

/* ---------- 记录 ---------- */
const records = ref<BackupRecordRow[]>([])
const recordsTotal = ref(0)
const recordsPage = ref(1)
const recordsPageSize = ref(20)
const recordsLoading = ref(false)

/* ---------- 还原向导 ---------- */
const wizardOpen = ref(false)
const serverBackups = ref<ServerBackupSummary[]>([])
const plan = ref<BackupRestorePlan | null>(null)
const uploadRestoring = ref(false)

async function loadStatus() {
  statusLoading.value = true
  try {
    const s = await backupApi.getStatus()
    status.value = s as unknown as Record<string, unknown>
  } catch {
    status.value = null
  } finally {
    statusLoading.value = false
  }
}
async function loadSchedules() {
  try {
    const res = await backupApi.listSchedules()
    schedules.value = res.tasks ?? []
  } catch { schedules.value = [] }
}
async function loadSettings() {
  try {
    settings.value = await backupApi.getSettings()
  } catch { settings.value = null }
}
async function loadServerBackups() {
  try {
    const res = await backupApi.listServerBackups()
    serverBackups.value = (res.backups ?? []).map((b) => ({
      filename: b.filename, size: b.size, created_at: b.created_at,
    }))
  } catch { serverBackups.value = [] }
}

async function triggerFull() {
  busy.value = true
  try {
    const res = await backupApi.triggerFull({ remark: '手动全量备份' })
    activeTaskId.value = res.task_id
  } catch { busy.value = false; activeTaskId.value = null }
}
async function triggerIncremental() {
  busy.value = true
  try {
    const res = await backupApi.triggerIncremental({ remark: '手动增量备份' })
    activeTaskId.value = res.task_id
  } catch { busy.value = false; activeTaskId.value = null }
}

async function saveSchedule(data: { name: string; task_type: string; cron_expr: string; enabled: boolean }) {
  saving.value = true
  try {
    await backupApi.createSchedule(data)
    await loadSchedules()
  } finally { saving.value = false }
}
async function deleteSchedule(id: number) {
  try {
    await backupApi.deleteSchedule(id)
    await loadSchedules()
  } catch { /* ignore */ }
}
async function triggerScheduleNow() {
  const first = schedules.value.find((s) => s.enabled)
  if (first?.name) {
    await backupApi.triggerSchedule(first.name)
  } else {
    await triggerIncremental()
  }
}

async function validatePath(path: string) {
  try {
    const res = await backupApi.validatePath(path)
    return { valid: res.valid, error: res.error }
  } catch {
    return { valid: false, error: '校验失败' }
  }
}
async function savePath(path: string) {
  saving.value = true
  try {
    await backupApi.saveSettings({ backup_dir: path || undefined })
    await loadSettings()
  } finally { saving.value = false }
}

async function loadRecords(page = recordsPage.value) {
  recordsLoading.value = true
  try {
    const res = (await backupApi.getRecords(page, recordsPageSize.value)) as unknown as Record<string, unknown>
    const body = res as { records?: BackupRecordRow[]; data?: { records?: BackupRecordRow[] }; total?: number }
    records.value = (body.records ?? (body.data?.records as BackupRecordRow[] | undefined) ?? []) as BackupRecordRow[]
    recordsTotal.value = (typeof body.total === 'number' ? body.total : records.value.length)
    recordsPage.value = page
  } catch { records.value = [] } finally { recordsLoading.value = false }
}
function onRecordRestore(filename: string) {
  wizardOpen.value = true
  previewPlan(filename)
}
function onRecordDownload(filename: string) {
  // 下载沿用后端按名导出；此处仅保留入口占位
}

function openWizard() {
  wizardOpen.value = true
}
async function previewPlan(filename: string) {
  try {
    plan.value = await backupApi.restorePlan(filename)
  } catch {
    plan.value = { success: false, filename, error: '预览失败' }
  }
}
async function executeRestore(filename: string) {
  busy.value = true
  try {
    const res = await backupApi.asyncRestoreByName(filename)
    activeTaskId.value = res.task_id ?? null
  } catch { busy.value = false }
}
async function onUploadRestore(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  uploadRestoring.value = true
  busy.value = true
  try {
    const res = await backupApi.asyncImport(fd)
    activeTaskId.value = res.task_id ?? null
  } catch {
    uploadRestoring.value = false
    busy.value = false
  }
}

onMounted(() => {
  void loadStatus()
  void loadSchedules()
  void loadSettings()
  void loadServerBackups()
  void loadRecords(1)
})
</script>

<style scoped>
.bk-center { max-width: 1440px; margin: 0 auto; padding: 24px; }
.bk-head { margin-bottom: 24px; }
.bk-head-title { font-size: 28px; font-weight: 600; line-height: 36px; }
.bk-head-sub { margin-top: 6px; font-size: 13px; color: var(--color-text-secondary, #4e5969); }
.bk-section { margin-bottom: 24px; }
.bk-grid-two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
@media (max-width: 1023px) { .bk-grid-two { grid-template-columns: 1fr; } }
.bk-actions-row { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.bk-btn-primary { height: 40px; padding: 0 24px; border-radius: 8px; border: none; background: var(--color-primary, #2f7bff); color: #fff; font-size: 15px; font-weight: 500; cursor: pointer; }
.bk-btn-outline { height: 40px; padding: 0 24px; border-radius: 8px; border: 1px solid var(--color-border-strong, #c9cdd4); background: var(--color-surface, #fff); color: var(--color-primary, #2f7bff); font-size: 15px; cursor: pointer; display: inline-flex; align-items: center; }
.bk-upload-note { margin-top: 8px; font-size: 13px; color: var(--color-text-tertiary, #86909c); }
</style>