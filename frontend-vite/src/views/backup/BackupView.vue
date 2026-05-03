<template>
  <div class="bk-container">
    <div class="bk-card bk-card-main">
      <div class="bk-card-header">
        <HeaderTabs />
        <div class="bk-card-title-group">
          <div class="bk-icon-box bk-icon-blue">
            <i class="fas fa-database" />
          </div>
          <div>
            <h3>数据备份与恢复</h3>
            <small>备份系统全部数据，或从备份文件恢复</small>
          </div>
        </div>
      </div>

      <div class="bk-body">
        <!-- 左栏：一键备份 -->
        <div class="bk-col">
          <div class="bk-col-title"><i class="fas fa-download" /> 一键备份</div>
          <div class="bk-col-content">
            <!-- 数据库概览 -->
            <div class="bk-section">
              <div class="bk-section-label">数据库概览</div>
              <div v-if="tablesLoading" class="bk-loading-inline"><i class="fas fa-spinner fa-spin" /> 加载中...</div>
              <div v-else-if="tables.length" class="bk-table-stats">
                <div class="bk-stat-item">
                  <div class="bk-stat-val">{{ tables.length }}</div>
                  <div class="bk-stat-lb">数据表</div>
                </div>
                <div class="bk-stat-item">
                  <div class="bk-stat-val">{{ totalRows }}</div>
                  <div class="bk-stat-lb">总记录数</div>
                </div>
              </div>
              <div v-if="tables.length" class="bk-table-list">
                <div v-for="t in tables" :key="t.name" class="bk-table-row">
                  <span class="bk-table-name">{{ t.name }}</span>
                  <span class="bk-table-count">{{ t.rows >= 0 ? t.rows : '?' }} 行</span>
                </div>
              </div>
            </div>

            <!-- 备份模式切换 -->
            <div class="bk-section">
              <div class="bk-section-label">备份方式</div>
              <div class="bk-mode-switch">
                <button
                  :class="['bk-mode-btn', backupMode === 'custom' ? 'bk-mode-active' : '']"
                  @click="backupMode = 'custom'"
                >
                  <i class="fas fa-file-download" />
                  <span>自定义路径</span>
                  <small>下载到本地</small>
                </button>
                <button
                  :class="['bk-mode-btn', backupMode === 'default' ? 'bk-mode-active' : '']"
                  @click="switchToDefaultMode"
                >
                  <i class="fas fa-server" />
                  <span>默认路径</span>
                  <small>保存到服务器</small>
                </button>
              </div>
            </div>

            <!-- 备份设置 -->
            <div class="bk-section">
              <div class="bk-section-label">备份备注（可选）</div>
              <div class="bk-form-field">
                <input
                  v-model="backupRemark"
                  type="text"
                  class="bk-form-input"
                  placeholder="例如：日常备份 / 上线前备份"
                />
              </div>
              <!-- 自定义路径：下载按钮 -->
              <button
                v-if="backupMode === 'custom'"
                class="bk-action-btn bk-action-primary"
                :disabled="exporting"
                @click="handleExport"
              >
                <i :class="exporting ? 'fas fa-spinner fa-spin' : 'fas fa-download'" />
                {{ exporting ? '正在备份...' : '下载备份文件' }}
              </button>
              <!-- 默认路径：保存到服务器按钮 -->
              <button
                v-if="backupMode === 'default'"
                class="bk-action-btn bk-action-primary"
                :disabled="savingToServer"
                @click="handleSaveToServer"
              >
                <i :class="savingToServer ? 'fas fa-spinner fa-spin' : 'fas fa-server'" />
                {{ savingToServer ? '正在备份...' : '备份到服务器' }}
              </button>
              <!-- 增量备份按钮 -->
              <button
                v-if="backupMode === 'default'"
                class="bk-action-btn bk-action-secondary"
                :disabled="savingIncremental"
                @click="handleSaveIncremental"
              >
                <i :class="savingIncremental ? 'fas fa-spinner fa-spin' : 'fas fa-layer-group'" />
                {{ savingIncremental ? '正在增量备份...' : '增量备份' }}
              </button>
            </div>

            <!-- 保存成功提示 -->
            <div v-if="saveResult" class="bk-section">
              <div class="bk-result-card bk-result-success">
                <div class="bk-result-header">
                  <i class="fas fa-check-circle" /> 备份已保存
                </div>
                <div class="bk-result-stats">
                  <span>文件: <b>{{ saveResult.filename }}</b></span>
                  <span>{{ formatSize(saveResult.size) }}</span>
                  <span>{{ saveResult.format === 'zip' ? 'ZIP' : 'JSON' }}</span>
                  <span>{{ saveResult.table_count }} 表 / {{ saveResult.total_rows }} 条</span>
                </div>
                <!-- ZIP includes badges -->
                <div v-if="saveResult.format === 'zip' && saveResult.includes" class="bk-backup-includes" style="margin-top: 8px;">
                  <span v-if="saveResult.includes.filestore_count" class="bk-badge"><i class="fas fa-paperclip" /> {{ saveResult.includes.filestore_count }} 附件</span>
                  <span v-if="saveResult.includes.config_files?.length" class="bk-badge"><i class="fas fa-cog" /> {{ saveResult.includes.config_files.length }} 配置</span>
                  <span v-if="saveResult.includes.redis_rdb" class="bk-badge"><i class="fas fa-bolt" /> Redis</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 右栏 -->
        <div class="bk-col">
          <!-- 自定义路径模式：文件上传恢复 -->
          <template v-if="backupMode === 'custom'">
            <div class="bk-col-title"><i class="fas fa-upload" /> 一键恢复</div>
            <div class="bk-col-content">
              <!-- 上传文件 -->
              <div class="bk-section">
                <div class="bk-section-label">选择备份文件</div>
                <div
                  class="bk-drop-zone"
                  :class="{ 'bk-drop-active': dragOver }"
                  tabindex="0"
                  role="button"
                  aria-label="选择备份文件"
                  @click="fileInputRef?.click()"
                  @keydown.enter="fileInputRef?.click()"
                  @keydown.space.prevent="fileInputRef?.click()"
                  @dragover.prevent="dragOver = true"
                  @dragleave="dragOver = false"
                  @drop.prevent="handleDrop"
                >
                  <div v-if="selectedFile" class="bk-file-info">
                    <i class="fas fa-file-alt" />
                    <span class="bk-file-name">{{ selectedFile.name }}</span>
                    <span class="bk-file-size">({{ formatSize(selectedFile.size) }})</span>
                    <button class="bk-file-clear" @click.stop="clearFile"><i class="fas fa-times" /></button>
                  </div>
                  <div v-else class="bk-drop-hint">
                    <i class="fas fa-cloud-upload-alt" />
                    <span>拖拽 .zip / .json 备份文件到此处，或点击选择</span>
                  </div>
                </div>
                <input ref="fileInputRef" type="file" accept=".zip,.json" style="display: none" @change="onFileSelect" />
              </div>

              <!-- 验证结果 -->
              <div v-if="validationResult" class="bk-section">
                <div class="bk-section-label">备份文件信息</div>
                <div class="bk-validate-card">
                  <div class="bk-validate-grid">
                    <div><div class="bk-det-lb">格式</div><div class="bk-det-vl">{{ validationResult.format === 'zip' ? 'ZIP（完整备份）' : 'JSON（仅数据库）' }}</div></div>
                    <div><div class="bk-det-lb">备份时间</div><div class="bk-det-vl">{{ validationResult.exported_at || '-' }}</div></div>
                    <div><div class="bk-det-lb">备份人</div><div class="bk-det-vl">{{ validationResult.exported_by || '-' }}</div></div>
                    <div><div class="bk-det-lb">数据表数</div><div class="bk-det-vl">{{ validationResult.table_count }}</div></div>
                    <div><div class="bk-det-lb">总记录数</div><div class="bk-det-vl">{{ validationResult.total_rows }}</div></div>
                    <div v-if="validationResult.checksums_ok !== null && validationResult.checksums_ok !== undefined"><div class="bk-det-lb">校验和</div><div class="bk-det-vl" :style="{ color: validationResult.checksums_ok ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">{{ validationResult.checksums_ok ? '通过' : '不匹配' }}</div></div>
                  </div>
                  <div v-if="validationResult.remark" class="bk-validate-remark">
                    <i class="fas fa-comment" /> {{ validationResult.remark }}
                  </div>
                  <!-- ZIP-specific: included components -->
                  <div v-if="validationResult.zip_contents" class="bk-validate-remark" style="margin-top: 8px;">
                    <div style="display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;">
                      <span :style="{ color: validationResult.zip_contents.has_database ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
                        <i :class="validationResult.zip_contents.has_database ? 'fas fa-check-circle' : 'fas fa-times-circle'" /> 数据库
                      </span>
                      <span :style="{ color: validationResult.zip_contents.has_filestore ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
                        <i :class="validationResult.zip_contents.has_filestore ? 'fas fa-check-circle' : 'fas fa-minus-circle'" /> 附件({{ validationResult.zip_contents.filestore_count || 0 }})
                      </span>
                      <span :style="{ color: validationResult.zip_contents.has_config ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
                        <i :class="validationResult.zip_contents.has_config ? 'fas fa-check-circle' : 'fas fa-minus-circle'" /> 配置
                      </span>
                      <span :style="{ color: validationResult.zip_contents.has_redis ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
                        <i :class="validationResult.zip_contents.has_redis ? 'fas fa-check-circle' : 'fas fa-minus-circle'" /> Redis
                      </span>
                    </div>
                  </div>
                  <div v-if="missingTables.length" class="bk-validate-warn">
                    <i class="fas fa-exclamation-triangle" /> {{ missingTables.length }} 个表在当前数据库中不存在：{{ missingTables.join(', ') }}
                  </div>
                  <div v-if="validationResult.checksum_errors?.length" class="bk-validate-warn">
                    <i class="fas fa-exclamation-triangle" /> {{ validationResult.checksum_errors.join('; ') }}
                  </div>
                </div>
                <button class="bk-action-btn bk-action-danger" :disabled="importing" @click="handleRestore">
                  <i :class="importing ? 'fas fa-spinner fa-spin' : 'fas fa-undo-alt'" />
                  {{ importing ? '正在恢复...' : '一键恢复全部数据' }}
                </button>
              </div>

              <!-- 恢复结果 -->
              <div v-if="restoreResult" class="bk-section">
                <div class="bk-section-label">恢复结果</div>
                <div class="bk-result-card" :class="restoreResult.errors?.length || restoreResult.results?.warnings?.length ? 'bk-result-partial' : 'bk-result-success'">
                  <div class="bk-result-header">
                    <i :class="restoreResult.errors?.length ? 'fas fa-exclamation-circle' : 'fas fa-check-circle'" />
                    {{ restoreResult.errors?.length ? '恢复完成（部分异常）' : '恢复成功' }}
                  </div>
                  <div class="bk-result-stats">
                    <span v-if="restoreResult.format === 'zip'">ZIP 完整备份恢复</span>
                    <span v-else>共恢复 <b>{{ restoreResult.total_inserted }}</b> 条记录</span>
                    <span v-if="restoreResult.results?.database?.status" class="bk-result-db-status">数据库: {{ restoreResult.results.database.status }}</span>
                    <span v-if="restoreResult.results?.filestore?.restored" class="bk-result-fs-status">附件: {{ restoreResult.results.filestore.restored }} 个</span>
                    <span v-if="restoreResult.results?.config?.restored?.length" class="bk-result-cfg-status">配置: {{ restoreResult.results.config.restored.length }} 个文件</span>
                  </div>
                  <div v-if="restoreResult.results?.warnings?.length" class="bk-result-errors" style="color: var(--color-warning-500);">
                    <div v-for="w in restoreResult.results.warnings" :key="w" class="bk-result-err-item">{{ w }}</div>
                  </div>
                  <div v-if="restoreResult.errors?.length" class="bk-result-errors">
                    <div v-for="e in restoreResult.errors" :key="e" class="bk-result-err-item">{{ e }}</div>
                  </div>
                </div>
                <!-- 验证报告 -->
                <div v-if="restoreResult.results?.verification || restoreResult.verification" class="bk-verify-card">
                  <div class="bk-verify-title">
                    <i :class="(restoreResult.results?.verification || restoreResult.verification).overall_pass ? 'fas fa-shield-alt' : 'fas fa-shield-alt bk-verify-fail'" />
                    数据完整性验证
                  </div>
                  <div class="bk-verify-summary">
                    <span :class="(restoreResult.results?.verification || restoreResult.verification).l1_row_count?.mismatch?.length ? 'bk-verify-warn' : 'bk-verify-ok'">
                      L1 行数比对: {{ (restoreResult.results?.verification || restoreResult.verification).l1_row_count?.summary || '未执行' }}
                    </span>
                    <span :class="(restoreResult.results?.verification || restoreResult.verification).l2_fingerprint?.tables_checked ? 'bk-verify-ok' : ''">
                      L2 指纹校验: {{ (restoreResult.results?.verification || restoreResult.verification).l2_fingerprint?.tables_checked || 0 }} 表已检查
                    </span>
                    <span>
                      L3 抽样验证: {{ (restoreResult.results?.verification || restoreResult.verification).l3_sampling?.tables_checked || 0 }} 表已抽样
                    </span>
                  </div>
                  <!-- L1 mismatch details -->
                  <div v-if="(restoreResult.results?.verification || restoreResult.verification).l1_row_count?.mismatch?.length" class="bk-verify-mismatches">
                    <div v-for="m in (restoreResult.results?.verification || restoreResult.verification).l1_row_count.mismatch" :key="m.table" class="bk-verify-mismatch-item">
                      <b>{{ m.table }}</b>: 期望 {{ m.expected }} 行，实际 {{ m.actual }} 行
                    </div>
                  </div>
                  <!-- L2 fingerprint details -->
                  <div v-if="(restoreResult.results?.verification || restoreResult.verification).l2_fingerprint?.results?.length" class="bk-verify-fp-list">
                    <div v-for="fp in (restoreResult.results?.verification || restoreResult.verification).l2_fingerprint.results" :key="fp.table" class="bk-verify-fp-item">
                      <span :class="fp.match === true ? 'bk-verify-ok' : fp.match === false ? 'bk-verify-fail' : ''">
                        <i :class="fp.match === true ? 'fas fa-check' : fp.match === false ? 'fas fa-times' : 'fas fa-minus'" />
                        {{ fp.table }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 默认路径模式：服务器备份列表 -->
          <template v-if="backupMode === 'default'">
            <div class="bk-col-title"><i class="fas fa-folder-open" /> 服务器备份</div>
            <div class="bk-col-content">
              <div v-if="serverBackupsLoading" class="bk-loading-inline"><i class="fas fa-spinner fa-spin" /> 加载中...</div>

              <div v-else-if="!serverBackups.length" class="bk-empty-state">
                <i class="fas fa-inbox" />
                <p>暂无服务器备份</p>
                <small>点击左侧「备份到服务器」创建第一个备份</small>
              </div>

              <div v-else class="bk-backup-list">
                <div v-for="b in serverBackups" :key="b.filename" class="bk-backup-item">
                  <div class="bk-backup-header">
                    <div class="bk-backup-name">
                      <i class="fas fa-file-archive" />
                      <span>{{ b.filename }}</span>
                    </div>
                    <div class="bk-backup-actions">
                      <button class="bk-icon-btn bk-icon-btn-primary" :disabled="restoringFile === b.filename" @click="handleServerRestore(b.filename)" title="恢复">
                        <i :class="restoringFile === b.filename ? 'fas fa-spinner fa-spin' : 'fas fa-undo-alt'" />
                      </button>
                      <button class="bk-icon-btn bk-icon-btn-danger" :disabled="deletingFile === b.filename" @click="handleServerDelete(b.filename)" title="删除">
                        <i :class="deletingFile === b.filename ? 'fas fa-spinner fa-spin' : 'fas fa-trash-alt'" />
                      </button>
                    </div>
                  </div>
                  <div class="bk-backup-meta">
                    <span v-if="b.format" class="bk-backup-format">
                      <i :class="b.format === 'incremental' ? 'fas fa-layer-group' : b.format === 'zip' ? 'fas fa-file-archive' : 'fas fa-file-code'" />
                      {{ b.format === 'incremental' ? '增量' : b.format === 'zip' ? 'ZIP' : 'JSON' }}
                    </span>
                    <span v-if="b.exported_at"><i class="fas fa-clock" /> {{ b.exported_at }}</span>
                    <span v-if="b.exported_by"><i class="fas fa-user" /> {{ b.exported_by }}</span>
                    <span><i class="fas fa-table" /> {{ b.table_count }} 表 / {{ b.total_rows }} 条</span>
                    <span><i class="fas fa-weight" /> {{ formatSize(b.size) }}</span>
                  </div>
                  <!-- ZIP-specific includes badges -->
                  <div v-if="b.format === 'zip' && b.includes" class="bk-backup-includes">
                    <span v-if="b.includes.filestore_count" class="bk-badge"><i class="fas fa-paperclip" /> {{ b.includes.filestore_count }} 附件</span>
                    <span v-if="b.includes.config_files?.length" class="bk-badge"><i class="fas fa-cog" /> {{ b.includes.config_files.length }} 配置</span>
                    <span v-if="b.includes.redis_rdb" class="bk-badge"><i class="fas fa-bolt" /> Redis</span>
                  </div>
                  <!-- Incremental backup: base timestamp -->
                  <div v-if="b.format === 'incremental' && b.base_timestamp" class="bk-backup-includes">
                    <span class="bk-badge bk-badge-inc"><i class="fas fa-clock" /> 基于 {{ b.base_timestamp }}</span>
                  </div>
                  <div v-if="b.remark" class="bk-backup-remark">
                    <i class="fas fa-comment" /> {{ b.remark }}
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 确认恢复弹窗 -->
    <UiDialog v-model:open="showConfirmDialog" title="确认恢复数据" max-width-class="max-w-[480px]">
      <template #title-icon><i class="fas fa-exclamation-triangle" style="color: var(--color-danger-500);" /></template>
      <div class="bk-confirm-body">
        <div class="bk-confirm-icon"><i class="fas fa-exclamation-triangle" /></div>
        <div class="bk-confirm-text">
          <p><b>此操作将清除当前所有数据，并从备份文件恢复。</b></p>
          <p>该操作不可撤销，请确保已做好必要准备。</p>
          <p v-if="confirmTarget">{{ confirmTarget }}</p>
        </div>
      </div>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="showConfirmDialog = false">取消</UiButton>
        <UiButton variant="danger" size="sm" :disabled="importing || !!restoringFile" @click="confirmRestoreAction">
          <i :class="importing || restoringFile ? 'fas fa-spinner fa-spin' : 'fas fa-undo-alt'" />
          {{ importing || restoringFile ? '恢复中...' : '确认恢复' }}
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { backupApi } from '@/api'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import { showToast } from '@/composables/useToast'

// --- Tables overview ---
const queryClient = useQueryClient()
const tables = ref<{ name: string; rows: number }[]>([])
const tablesLoading = ref(false)
const totalRows = computed(() => tables.value.reduce((sum, t) => sum + (t.rows >= 0 ? t.rows : 0), 0))

async function loadTables() {
  tablesLoading.value = true
  try {
    const res = await backupApi.tables() as any
    if (res.success) tables.value = res.tables
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

function switchToDefaultMode() {
  backupMode.value = 'default'
  loadServerBackups()
}

// --- Custom path: export (download) ---
const exporting = ref(false)

async function handleExport() {
  exporting.value = true
  try {
    await backupApi.exportBackup(backupRemark.value)
    showToast('备份文件已下载', 'success')
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '备份失败', 'error')
  } finally {
    exporting.value = false
  }
}

// --- Default path: save to server ---
const savingToServer = ref(false)
const saveResult = ref<any>(null)

async function handleSaveToServer() {
  savingToServer.value = true
  saveResult.value = null
  try {
    const res = await backupApi.saveToServer(backupRemark.value) as any
    if (res.success) {
      saveResult.value = res
      showToast('备份已保存到服务器', 'success')
      loadServerBackups()
      loadTables()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '保存到服务器失败', 'error')
  } finally {
    savingToServer.value = false
  }
}

// --- Custom path: file upload & restore ---
const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const validationResult = ref<any>(null)
const importing = ref(false)
const restoreResult = ref<any>(null)

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) setFile(input.files[0])
}

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) setFile(file)
}

function setFile(file: File) {
  if (!file.name.endsWith('.json') && !file.name.endsWith('.zip')) {
    showToast('请选择 .zip 或 .json 备份文件', 'warning')
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
  if (fileInputRef.value) fileInputRef.value.value = ''
}

async function validateFile(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await backupApi.validateFile(formData) as any
    if (res.success) validationResult.value = res.summary
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '验证失败', 'error')
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
    const res = await backupApi.listServerBackups() as any
    if (res.success) serverBackups.value = res.backups
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '加载服务器备份列表失败', 'error')
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
    const res = await backupApi.deleteServerBackup(filename) as any
    if (res.success) {
      showToast('备份已删除', 'success')
      serverBackups.value = serverBackups.value.filter(b => b.filename !== filename)
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '删除失败', 'error')
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
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const res = await backupApi.importBackup(formData) as any
    restoreResult.value = res
    if (res.success) {
      const msg = res.format === 'zip'
        ? '恢复成功（完整备份）'
        : `恢复成功，共 ${res.total_inserted} 条记录`
      showToast(msg, (res.errors?.length || res.results?.warnings?.length) ? 'warning' : 'success')
      queryClient.invalidateQueries()
      loadTables()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '恢复失败', 'error')
  } finally {
    importing.value = false
  }
}

async function doServerRestore() {
  if (!pendingRestoreFilename) return
  restoringFile.value = pendingRestoreFilename
  try {
    const res = await backupApi.restoreServerBackup(pendingRestoreFilename) as any
    if (res.success) {
      const msg = res.format === 'zip'
        ? '恢复成功（完整备份）'
        : `恢复成功，共 ${res.total_inserted} 条记录`
      showToast(msg, (res.errors?.length || res.results?.warnings?.length) ? 'warning' : 'success')
      queryClient.invalidateQueries()
      loadTables()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '恢复失败', 'error')
  } finally {
    restoringFile.value = ''
    pendingRestoreFilename = ''
  }
}

// --- Incremental backup ---
const savingIncremental = ref(false)
const incrementalResult = ref<any>(null)

async function handleSaveIncremental() {
  savingIncremental.value = true
  try {
    const res = await backupApi.saveIncremental(backupRemark.value) as any
    if (res.success) {
      showToast(`增量备份成功: ${res.filename} (${res.total_rows} 条变更)`, 'success')
      incrementalResult.value = res
      loadServerBackups()
      loadTables()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '增量备份失败', 'error')
  } finally {
    savingIncremental.value = false
  }
}

async function doIncrementalRestore() {
  if (!pendingRestoreFilename) return
  restoringFile.value = pendingRestoreFilename
  try {
    const res = await backupApi.restoreIncremental(pendingRestoreFilename) as any
    restoreResult.value = res
    if (res.success) {
      const msg = `增量恢复成功，共更新 ${res.total_upserted || 0} 条记录`
      showToast(msg, 'success')
      queryClient.invalidateQueries()
      loadTables()
      loadServerBackups()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '增量恢复失败', 'error')
  } finally {
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
</script>

<style scoped>
/* === Layout === */
.bk-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
.bk-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light);
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.bk-card:hover {
  box-shadow: var(--shadow-md);
}

.bk-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* === Header === */
.bk-card-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px 10px;
  flex-shrink: 0;
  gap: 12px;
}

.bk-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

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

/* === Section === */
.bk-section {
  margin-bottom: 20px;
}

.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* === Table Stats === */
.bk-table-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.bk-stat-item {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-radius: var(--radius-sm);
  padding: 12px 18px;
  flex: 1;
  text-align: center;
}

.bk-stat-val {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-primary-600);
}

.bk-stat-lb {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

/* === Table List === */
.bk-table-list {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
}

.bk-table-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light);
  transition: background 0.2s ease, transform 0.2s ease;
}

.bk-table-row:last-child {
  border-bottom: none;
}

.bk-table-row:hover {
  background: var(--color-primary-50);
  transform: translateX(4px);
}

.bk-table-name {
  font-weight: 500;
  color: var(--color-text);
  font-family: monospace;
  font-size: 12px;
}

.bk-table-count {
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* === Mode Switch === */
.bk-mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.bk-mode-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: white;
  cursor: pointer;
  transition: all 0.3s ease;
}

.bk-mode-btn span {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.bk-mode-btn small {
  font-size: 11px;
  color: var(--color-text-muted);
}

.bk-mode-btn i {
  font-size: 18px;
  color: var(--color-text-muted);
  transition: color 0.3s ease;
}

.bk-mode-btn:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}

.bk-mode-btn:hover i {
  color: var(--color-primary-500);
}

.bk-mode-active {
  border-color: var(--color-primary-400);
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  box-shadow: var(--shadow-sm);
}

.bk-mode-active i {
  color: var(--color-primary-600);
}

.bk-mode-active span {
  color: var(--color-primary-700);
}

/* === Form === */
.bk-form-field {
  margin-bottom: 12px;
}

.bk-form-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);
  font-size: 14px;
  outline: none;
  transition: all 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
  min-height: 44px;
}

.bk-form-input:focus {
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

.bk-form-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* === Action Buttons === */
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
  transition: all 0.3s ease;
}

.bk-action-primary {
  color: var(--color-primary-600);
  background: linear-gradient(135deg, var(--color-primary-50), white);
  border-color: var(--color-primary-200);
}

.bk-action-primary:hover:not(:disabled) {
  background: var(--color-primary-100);
  border-color: var(--color-primary-400);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

.bk-action-danger {
  color: var(--color-danger-500);
  border-color: var(--color-danger-200);
  background: var(--color-danger-50);
}

.bk-action-danger:hover:not(:disabled) {
  background: var(--color-danger-100);
  border-color: var(--color-danger-400);
  transform: translateY(-1px);
}

.bk-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

/* === Drop Zone === */
.bk-drop-zone {
  border: 2px dashed var(--color-ocean-light);
  border-radius: var(--radius-input);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background: white;
}

.bk-drop-zone:hover,
.bk-drop-active {
  border-color: var(--color-ocean-deep);
  background: var(--color-ocean-light);
}

.bk-drop-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
}

.bk-drop-hint i {
  font-size: 28px;
  color: var(--color-primary-300);
}

.bk-file-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text);
  font-size: 14px;
}

.bk-file-info > i {
  color: var(--color-success-500);
}

.bk-file-name {
  font-weight: 600;
}

.bk-file-size {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.bk-file-clear {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 50%;
  transition: all 0.2s ease;
}

.bk-file-clear:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

/* === Validate Card === */
.bk-validate-card {
  padding: 14px 16px;
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-surface));
  border: 1px solid var(--color-primary-200);
  border-radius: var(--radius-sm);
  margin-bottom: 12px;
}

.bk-validate-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.bk-det-lb {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.bk-det-vl {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}

.bk-validate-remark {
  margin-top: 10px;
  padding: 8px 12px;
  background: white;
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.bk-validate-remark i {
  margin-right: 4px;
  color: var(--color-primary-400);
}

.bk-validate-warn {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--color-warning-50);
  border-radius: 8px;
  font-size: 12px;
  color: var(--color-warning-700);
}

.bk-validate-warn i {
  margin-right: 4px;
}

/* === Result Card === */
.bk-result-card {
  padding: 16px;
  border-radius: var(--radius-sm);
  border: 1px solid;
}

.bk-result-success {
  background: linear-gradient(135deg, var(--color-success-50), var(--color-surface));
  border-color: var(--color-success-200);
}

.bk-result-partial {
  background: linear-gradient(135deg, var(--color-warning-50), var(--color-surface));
  border-color: var(--color-warning-200);
}

.bk-result-header {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.bk-result-success .bk-result-header i { color: var(--color-success-500); }
.bk-result-partial .bk-result-header i { color: var(--color-warning-500); }

.bk-result-stats {
  font-size: 13px;
  color: var(--color-text-secondary);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.bk-result-err-count {
  color: var(--color-danger-500);
  font-weight: 600;
}

.bk-result-errors {
  margin-top: 10px;
  max-height: 120px;
  overflow-y: auto;
}

.bk-result-err-item {
  font-size: 12px;
  color: var(--color-danger-600);
  padding: 4px 0;
  border-top: 1px solid var(--color-danger-100);
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
  transition: all 0.3s ease;
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
  transition: all 0.2s ease;
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

.bk-result-db-status,
.bk-result-fs-status,
.bk-result-cfg-status {
  font-size: 12px;
  color: var(--color-success-600);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* === Verification Card === */
.bk-verify-card {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-neutral-50);
  border-radius: 10px;
  border: 1px solid var(--color-border-light);
}

.bk-verify-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-neutral-700);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.bk-verify-fail {
  color: var(--color-danger-500);
}

.bk-verify-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--color-neutral-600);
}

.bk-verify-ok {
  color: var(--color-success-600);
}

.bk-verify-warn {
  color: var(--color-warning-600);
}

.bk-verify-mismatches {
  margin-top: 6px;
  padding: 6px 8px;
  background: var(--color-warning-50);
  border-radius: 6px;
  font-size: 12px;
}

.bk-verify-mismatch-item {
  color: var(--color-warning-700);
  padding: 2px 0;
}

.bk-verify-fp-list {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.bk-verify-fp-item {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--color-neutral-100);
}

/* === Incremental Badge === */
.bk-badge-inc {
  background: var(--color-info-50);
  color: var(--color-info-600);
}

/* === Secondary Action Button === */
.bk-action-secondary {
  background: var(--color-neutral-100);
  color: var(--color-neutral-700);
  border: 1px solid var(--color-border-light);
  margin-top: 8px;
}

.bk-action-secondary:hover:not(:disabled) {
  background: var(--color-neutral-200);
}
</style>
