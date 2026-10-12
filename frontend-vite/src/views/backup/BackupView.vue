<template>
  <div class="page-card page-card-main bk-root">
    <div class="page-card-header">
      <div class="bk-head">
        <div class="bk-head-title">数据备份中心</div>
        <div class="bk-head-sub">生产环境 · 数据备份与恢复</div>
      </div>
      <div class="bk-header-actions">
        <button class="bk-btn bk-btn-primary" @click="openWizard">还原备份</button>
        <label class="bk-btn bk-btn-outline">
          从文件上传还原
          <input type="file" accept=".zip,.json,.gz" hidden @change="onUploadRestore" />
        </label>
      </div>
    </div>

    <div class="page-card-body">
      <section class="bk-section">
        <BackupOverviewCards :status="status" :loading="statusLoading" />
      </section>

      <section class="bk-section">
        <BackupActions
          :busy="busy"
          :task="taskState"
          :on-full="triggerFull"
          no-task-hint="同一时刻至多执行一个任务"
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
        <RestoreConfirmDialog
          :open="wizardOpen"
          :initial-filename="wizardInitialFilename"
          :plan="plan"
          :plan-loading="planLoading"
          :task="taskState"
          :result="restoreResult"
          :on-plan="previewPlan"
          :on-execute="executeRestore"
          @close="wizardOpen = false"
        />
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
          @delete="onRecordDelete"
        />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { backupApi } from '@/api'
import type { BackupRestorePlan, BackupScheduleItem, BackupSettings } from '@/api/backup'
import { toast } from '@/composables/useToast'
import BackupOverviewCards from '@/components/backup/BackupOverviewCards.vue'
import BackupActions from '@/components/backup/BackupActions.vue'
import ScheduleConfig from '@/components/backup/ScheduleConfig.vue'
import PathSettings from '@/components/backup/PathSettings.vue'
import RestoreConfirmDialog, { type RestoreExecuteOptions } from '@/components/backup/RestoreConfirmDialog.vue'
import BackupRecordTable, { type BackupRecordRow } from '@/components/backup/BackupRecordTable.vue'
import { useBackupTask, type BackupTaskState } from '@/components/backup/composables/useBackupTask'

/* ---------- 概览 / 调度 / 设置 ---------- */
const status = ref<Record<string, unknown> | null>(null)
const statusLoading = ref(false)
const schedules = ref<BackupScheduleItem[]>([])
const settings = ref<BackupSettings | null>(null)
const saving = ref(false)

/* ---------- 任务进度（备份 + 还原 + 上传共用统一轮询） ---------- */
const activeTaskId = ref<string | null>(null)
const busy = ref(false)
const uploadRestoring = ref(false)
/** 当前任务类型，用于终态 toast 文案（备份/还原共用同一轮询） */
const taskKind = ref<'备份' | '还原'>('备份')
/** 还原任务终态快照：统一轮询终态会复位 taskState，弹窗据此渲染结果报告 */
const restoreResult = ref<BackupTaskState | null>(null)
/**
 * 标记「当前在跑的任务是否由还原弹窗发起」。
 * 备份任务、上传文件还原与弹窗共用同一套轮询与终态回调，若不隔离，
 * 备份完成会把弹窗顶到「还原完成」，向操作者展示从未发生的成功报告。
 */
const restoreFromDialog = ref(false)

/** 后端 409/500 的 detail 形如 {code, message}，取不到时回退默认文案 */
function errText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return fallback
}

const { state: taskState } = useBackupTask(
  () => activeTaskId.value,
  () => {
    // 统一轮询在终态会复位任务状态，先快照再复位，否则弹窗结果报告会丢失。
    // 仅快照弹窗发起的还原，避免备份/上传还原的终态污染弹窗结果报告
    if (restoreFromDialog.value) {
      restoreResult.value = { ...taskState.value }
      restoreFromDialog.value = false
    }
    busy.value = false
    uploadRestoring.value = false
    // B7 修复：终态清空 activeTaskId，否则备份按钮终身禁用（task?.taskId
    // 恒真），必须刷新页面才能再次备份
    activeTaskId.value = null
    toast.success(`${taskKind.value}任务已完成`)
    void loadStatus()
    void loadRecords()
  },
  (error: string) => {
    if (restoreFromDialog.value) {
      restoreResult.value = { ...taskState.value }
      restoreFromDialog.value = false
    }
    busy.value = false
    uploadRestoring.value = false
    activeTaskId.value = null
    toast.error(`${taskKind.value}任务失败：${error || '请查看服务器日志'}`)
    void loadStatus()
  },
)

/* ---------- 记录 ---------- */
const records = ref<BackupRecordRow[]>([])
const recordsTotal = ref(0)
const recordsPage = ref(1)
const recordsPageSize = ref(20)
const recordsLoading = ref(false)

/* ---------- 还原确认弹窗 ---------- */
const wizardOpen = ref(false)
const wizardInitialFilename = ref('')
const plan = ref<BackupRestorePlan | null>(null)
const planLoading = ref(false)

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

async function triggerFull(opts?: { password?: string; tables?: string[]; excludeTables?: string[] }) {
  busy.value = true
  taskKind.value = '备份'
  const partial = !!(opts?.tables?.length || opts?.excludeTables?.length)
  try {
    const res = await backupApi.triggerFull({
      remark: partial ? '手动表级备份' : '手动全量备份',
      // 表达「期望加密」的意图，最终是否加密由服务端总开关 BACKUP_ENCRYPTION_ENABLED 决定：
      // 开关关闭 → 后端忽略本字段产出明文；开关开启 → 有密码才加密。前端硬编码 false 会让
      // 开关重新打开后 UI 永远产不出加密包，故此处保持 true（由服务端裁决）。
      encrypt: true,
      password: opts?.password,
      tables: opts?.tables?.length ? opts.tables : undefined,
      exclude_tables: opts?.excludeTables?.length ? opts.excludeTables : undefined,
    })
    activeTaskId.value = res.task_id
    toast.info(partial ? '表级备份任务已触发' : '全量备份任务已触发')
  } catch (e) {
    busy.value = false
    activeTaskId.value = null
    toast.error(errText(e, '触发全量备份失败，请稍后重试'))
  }
}
async function saveSchedule(data: { name: string; task_type: string; cron_expr: string; enabled: boolean }) {
  saving.value = true
  try {
    await backupApi.createSchedule(data)
    await loadSchedules()
  } catch (e) {
    // 没有 catch 时后端的 400（cron 非法等）会变成未处理的 promise rejection：
    // 界面既不报错也不关闭，运维只看到"点了没反应"，无从修正输入
    toast.error(errText(e, '保存定时任务失败'))
  } finally { saving.value = false }
}
async function deleteSchedule(id: number) {
  try {
    await backupApi.deleteSchedule(id)
    await loadSchedules()
  } catch (e) {
    toast.error(errText(e, '删除定时任务失败'))
  }
}
async function triggerScheduleNow() {
  const first = schedules.value.find((s) => s.enabled)
  if (!first?.name) {
    // 无启用的定时任务时不回退触发任何备份（全量属重操作，静默发起会让用户意外）
    toast.info('当前没有启用的定时任务')
    return
  }
  await backupApi.triggerSchedule(first.name)
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
    // 空字符串表示恢复默认系统路径(后端据此重置 backup_dir)
    await backupApi.saveSettings({ backup_dir: path })
    await loadSettings()
  } catch (e) {
    // 同 saveSchedule：无 catch 会把 400（路径非法/不可写）吞成"点了没反应"
    toast.error(errText(e, '保存备份路径失败'))
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
  wizardInitialFilename.value = filename
  restoreResult.value = null
  plan.value = null
  wizardOpen.value = true
}
async function onRecordDownload(filename: string) {
  try {
    await backupApi.downloadByName(filename)
  } catch (e) {
    toast.error(errText(e, '下载失败，请稍后重试'))
  }
}

async function onRecordDelete(filename: string) {
  if (!window.confirm(`确定删除备份文件「${filename}」？该操作不可恢复。`)) return
  try {
    await backupApi.deleteServerBackup(filename)
    toast.success('备份文件已删除')
    void loadRecords()
    void loadStatus()
  } catch (e) {
    toast.error(errText(e, '删除失败，请稍后重试'))
  }
}

function openWizard() {
  wizardInitialFilename.value = ''
  restoreResult.value = null
  plan.value = null
  wizardOpen.value = true
}
/** 预览请求序号：快速切换备份点时只接受最后一次的响应，避免展示错配的影响范围 */
let planSeq = 0
async function previewPlan(filename: string, password?: string) {
  const seq = ++planSeq
  planLoading.value = true
  plan.value = null
  try {
    const res = await backupApi.restorePlan(filename, password)
    if (seq === planSeq) plan.value = res
  } catch {
    if (seq === planSeq) plan.value = { success: false, filename, error: '预览失败' }
  } finally {
    if (seq === planSeq) planLoading.value = false
  }
}
async function executeRestore(filename: string, opts?: RestoreExecuteOptions): Promise<boolean> {
  busy.value = true
  taskKind.value = '还原'
  try {
    const res = await backupApi.asyncRestoreByName(filename, {
      confirmSensitive: opts?.confirmSensitive ?? false,
    })
    if (!res.task_id) {
      // 无 task_id 则轮询无从启动、弹窗会永久停在进度态，按入队失败处理
      busy.value = false
      toast.error('还原任务未返回任务号，请稍后重试')
      return false
    }
    activeTaskId.value = res.task_id
    restoreFromDialog.value = true
    return true
  } catch (e) {
    busy.value = false
    toast.error(errText(e, '触发还原失败，请稍后重试'))
    return false
  }
}
async function onUploadRestore(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  uploadRestoring.value = true
  busy.value = true
  taskKind.value = '还原'
  try {
    const res = await backupApi.asyncImport(fd)
    activeTaskId.value = res.task_id ?? null
  } catch (err) {
    uploadRestoring.value = false
    busy.value = false
    toast.error(errText(err, '上传还原请求失败'))
  }
}

onMounted(() => {
  void loadStatus()
  void loadSchedules()
  void loadSettings()
  void loadRecords(1)
})
</script>

<style scoped>
/* ============ 骨架：套用全局 Plush Cute page-card 体系 ============ */
.bk-root {
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
  color: var(--color-text);
}

/* 标题区（对齐采购页 .page-card-header 布局） */
.bk-head { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.bk-head-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: -0.01em;
  line-height: 1.35;
}
.bk-head-sub {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.bk-header-actions { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }

/* ============ 统一按钮（对齐采购页 .pc-btn：描边 + Plush Cute 语义色） ============ */
.bk-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-button, 14px);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  line-height: 1.2;
  cursor: pointer;
  background: #ffffff;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}
.bk-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.bk-btn-primary {
  color: #fff;
  border-color: transparent;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.24);
}
.bk-btn-primary:hover:not(:disabled) {
  box-shadow: 0 6px 18px rgba(91, 141, 239, 0.32);
  transform: translateY(-1px);
}
.bk-btn-outline { color: var(--color-primary-600); }
.bk-btn-outline:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-1px);
}

.bk-upload-note { margin-top: 8px; font-size: 13px; color: var(--color-text-muted); }
.bk-section { margin-bottom: 20px; }
.bk-grid-two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 1023px) { .bk-grid-two { grid-template-columns: 1fr; } }

/* 入场动效，对齐全局 animate-fade-in */
.bk-section { animation: fadeIn 0.3s ease; }
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>