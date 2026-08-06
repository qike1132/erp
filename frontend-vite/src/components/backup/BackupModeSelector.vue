<template>
  <div class="bk-col-content">
    <!-- 数据库概览 -->
    <div class="bk-section">
      <div class="bk-section-label">数据库概览</div>
      <div v-if="tablesLoading" class="bk-loading-inline"><UiSpinner /></div>
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
          @click="$emit('mode-change', 'custom')"
        >
          <i class="fas fa-file-download" />
          <span>自定义路径</span>
          <small>下载到本地</small>
        </button>
        <button
          :class="['bk-mode-btn', backupMode === 'default' ? 'bk-mode-active' : '']"
          @click="$emit('mode-change', 'default')"
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
          :value="backupRemark"
          type="text"
          class="bk-form-input"
          placeholder="例如：日常备份 / 上线前备份"
          @input="$emit('update:backupRemark', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <!-- 自定义路径：下载按钮 -->
      <button
        v-if="backupMode === 'custom'"
        class="bk-action-btn bk-action-primary"
        :disabled="exporting"
        @click="$emit('export')"
      >
        <UiLoadingIcon :loading="exporting" icon="download" />
        {{ exporting ? '正在备份...' : '下载备份文件' }}
      </button>
      <!-- 默认路径：保存到服务器按钮 -->
      <button
        v-if="backupMode === 'default'"
        class="bk-action-btn bk-action-primary"
        :disabled="savingToServer"
        @click="$emit('save-to-server')"
      >
        <UiLoadingIcon :loading="savingToServer" icon="server" />
        {{ savingToServer ? '正在备份...' : '备份到服务器' }}
      </button>
      <!-- 增量备份按钮 -->
      <button
        v-if="backupMode === 'default'"
        class="bk-action-btn bk-action-secondary"
        :disabled="savingIncremental"
        @click="$emit('save-incremental')"
      >
        <UiLoadingIcon :loading="savingIncremental" icon="layer-group" />
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
</template>

<script setup lang="ts">
import { computed } from 'vue'

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

const props = defineProps<{
  tables: { name: string; rows: number }[]
  tablesLoading: boolean
  backupMode: 'custom' | 'default'
  backupRemark: string
  exporting: boolean
  savingToServer: boolean
  savingIncremental: boolean
  saveResult: BackupSaveResult | null
}>()

defineEmits<{
  (e: 'update:backupRemark', value: string): void
  (e: 'mode-change', mode: 'custom' | 'default'): void
  (e: 'export'): void
  (e: 'save-to-server'): void
  (e: 'save-incremental'): void
}>()

const totalRows = computed(() =>
  props.tables.reduce((sum, t) => sum + (t.rows >= 0 ? t.rows : 0), 0),
)

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

.bk-loading-inline {
  text-align: center;
  padding: 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

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
  transition: border-color 0.3s ease, background 0.3s ease;
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
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
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

.bk-result-card {
  padding: 16px;
  border-radius: var(--radius-sm);
  border: 1px solid;
}

.bk-result-success {
  background: linear-gradient(135deg, var(--color-success-50), var(--color-surface));
  border-color: var(--color-success-200);
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

.bk-result-stats {
  font-size: 13px;
  color: var(--color-text-secondary);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

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
</style>
