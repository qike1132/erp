<template>
  <div class="bk-col-title"><FontAwesomeIcon icon="folder-open" /> 服务器备份</div>
  <div class="bk-col-content">
    <!-- 服务器恢复进度条 -->
    <RestoreProgressBar
      v-if="restoreTaskId && backupMode === 'default'"
      :task-id="restoreTaskId"
      @completed="emit('restore-completed', $event)"
      @failed="emit('restore-failed', $event)"
    />

    <div v-if="loading" class="bk-loading-inline"><UiSpinner /></div>

    <div v-else-if="!backups.length" class="bk-empty-state">
      <FontAwesomeIcon icon="inbox" />
      <p>暂无服务器备份</p>
      <small>点击左侧「备份到服务器」创建第一个备份</small>
    </div>

    <div v-else class="bk-backup-list">
      <div v-for="b in backups" :key="b.filename" class="bk-backup-item">
        <div class="bk-backup-header">
          <div class="bk-backup-name">
            <FontAwesomeIcon icon="file-archive" />
            <span>{{ b.filename }}</span>
          </div>
          <div class="bk-backup-actions">
            <button class="bk-icon-btn bk-icon-btn-primary" :disabled="restoringFile === b.filename" @click="emit('restore', b.filename)" title="恢复" aria-label="恢复">
              <UiLoadingIcon :loading="restoringFile === b.filename" icon="undo-alt" />
            </button>
            <button class="bk-icon-btn bk-icon-btn-danger" :disabled="deletingFile === b.filename" @click="emit('delete', b.filename)" title="删除" aria-label="删除">
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

<script setup lang="ts">
// 服务器备份列表面板（从 BackupView.vue 抽出，模板原样搬移）
import RestoreProgressBar from '@/components/backup/RestoreProgressBar.vue'
import type { ServerBackupItem } from '../composables/useBackupCenter'
import type { RestoreResult } from '@/components/backup/composables/useRestorePolling'

defineProps<{
  backups: ServerBackupItem[]
  loading: boolean
  restoringFile: string
  deletingFile: string
  backupMode: 'custom' | 'default'
  restoreTaskId: string | null
}>()

const emit = defineEmits<{
  restore: [filename: string]
  delete: [filename: string]
  'restore-completed': [result: RestoreResult | null]
  'restore-failed': [error: string]
}>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
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
</style>
