<template>
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
          <button class="bk-file-clear" aria-label="关闭" @click.stop="handleClear"><i class="fas fa-times" /></button>
        </div>
        <div v-else class="bk-drop-hint">
          <i class="fas fa-cloud-upload-alt" />
          <span>拖拽 .zip / .json / .gz 备份文件到此处，或点击选择</span>
        </div>
      </div>
      <input ref="fileInputRef" type="file" accept=".zip,.json,.gz" style="display: none" @change="onFileSelect" />
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
      <button class="bk-action-btn bk-action-danger" :disabled="importing" @click="$emit('restore')">
        <UiLoadingIcon :loading="importing" icon="undo-alt" />
        {{ importing ? '正在恢复...' : '一键恢复全部数据' }}
      </button>

      <!-- 实时进度条 -->
      <RestoreProgressBar
        v-if="restoreTaskId"
        :task-id="restoreTaskId"
        @completed="$emit('restore-completed', $event)"
        @failed="$emit('restore-failed', $event)"
      />
    </div>

    <!-- 恢复结果 -->
    <div v-if="restoreResult" class="bk-section">
      <div class="bk-section-label">恢复结果</div>
      <div class="bk-result-card" :class="restoreResult.errors?.length || restoreResult.warnings?.length || restoreResult.results?.warnings?.length ? 'bk-result-partial' : 'bk-result-success'">
        <div class="bk-result-header">
          <i :class="restoreResult.errors?.length ? 'fas fa-exclamation-circle' : 'fas fa-check-circle'" />
          {{ restoreResult.errors?.length ? '恢复完成（部分异常）' : '恢复成功' }}
        </div>
        <div class="bk-result-stats">
          <span v-if="restoreResult.format === 'zip' || restoreResult.database || restoreResult.results?.database">ZIP 完整备份恢复 <template v-if="restoreResult.total_inserted">（{{ restoreResult.total_inserted }} 条记录）</template></span>
          <span v-else>共恢复 <b>{{ restoreResult.total_inserted }}</b> 条记录</span>
          <span v-if="(restoreResult.database || restoreResult.results?.database)?.status" class="bk-result-db-status">数据库: {{ (restoreResult.database || restoreResult.results?.database).status }}</span>
          <span v-if="restoreResult.results?.filestore?.restored" class="bk-result-fs-status">附件: {{ restoreResult.results.filestore.restored }} 个</span>
          <span v-if="restoreResult.results?.config?.restored?.length" class="bk-result-cfg-status">配置: {{ restoreResult.results.config.restored.length }} 个文件</span>
        </div>
        <div v-if="(restoreResult.database || restoreResult.results?.database)?.errors" class="bk-result-errors" style="color: var(--color-danger-500);">
          <div class="bk-result-err-item" v-for="e in (Array.isArray((restoreResult.database || restoreResult.results?.database).errors) ? (restoreResult.database || restoreResult.results?.database).errors : [(restoreResult.database || restoreResult.results?.database).errors])" :key="e">{{ e }}</div>
        </div>
        <div v-if="(restoreResult.database || restoreResult.results?.database)?.error" class="bk-result-errors">
          <div class="bk-result-err-item">{{ (restoreResult.database || restoreResult.results?.database).error }}</div>
        </div>
        <div v-if="restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup" class="bk-pre-restore-info">
          <i class="fas fa-shield-alt" /> 安全备份: {{ (restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup).success ? '已创建' : '创建失败' }}
          <span v-if="(restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup).filename">({{ (restoreResult.pre_restore_backup || restoreResult.results?.pre_restore_backup).filename }})</span>
        </div>
        <div v-if="restoreResult.rollback || restoreResult.results?.rollback" class="bk-result-errors">
          <div class="bk-result-err-item" :style="{ color: (restoreResult.rollback || restoreResult.results?.rollback).success ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
            <i :class="(restoreResult.rollback || restoreResult.results?.rollback).success ? 'fas fa-check-circle' : 'fas fa-times-circle'" />
            回滚{{ (restoreResult.rollback || restoreResult.results?.rollback).success ? '成功' : '失败' }}
            <span v-if="(restoreResult.rollback || restoreResult.results?.rollback).error">: {{ (restoreResult.rollback || restoreResult.results?.rollback).error }}</span>
          </div>
        </div>
        <div v-if="(restoreResult.warnings || restoreResult.results?.warnings)?.length" class="bk-result-errors" style="color: var(--color-warning-500);">
          <div v-for="w in (restoreResult.warnings || restoreResult.results?.warnings)" :key="w" class="bk-result-err-item">{{ w }}</div>
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

<script setup lang="ts">
import { ref } from 'vue'
import RestoreProgressBar from '@/components/backup/RestoreProgressBar.vue'

defineProps<{
  selectedFile: File | null
  validationResult: any
  importing: boolean
  restoreResult: any
  restoreTaskId: string | null
  missingTables: string[]
}>()

const emit = defineEmits<{
  (e: 'file-select', file: File): void
  (e: 'file-clear'): void
  (e: 'restore'): void
  (e: 'restore-completed', result: any): void
  (e: 'restore-failed', error: string): void
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) emit('file-select', input.files[0])
}

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) emit('file-select', file)
}

function handleClear() {
  if (fileInputRef.value) fileInputRef.value.value = ''
  emit('file-clear')
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.bk-col-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}

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

.bk-drop-zone {
  border: 2px dashed var(--color-ocean-light);
  border-radius: var(--radius-input);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
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
  transition: background 0.2s ease, color 0.2s ease;
}

.bk-file-clear:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

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

.bk-result-success .bk-result-header i {
  color: var(--color-success-500);
}

.bk-result-partial .bk-result-header i {
  color: var(--color-warning-500);
}

.bk-result-stats {
  font-size: 13px;
  color: var(--color-text-secondary);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
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

.bk-pre-restore-info {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-info-600);
  display: flex;
  align-items: center;
  gap: 4px;
}

.bk-pre-restore-info i {
  color: var(--color-info-500);
}

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
</style>
