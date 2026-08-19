<template>
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
        <FontAwesomeIcon icon="comment" /> {{ validationResult.remark }}
      </div>
      <!-- ZIP-specific: included components -->
      <div v-if="validationResult.zip_contents" class="bk-validate-remark" style="margin-top: 8px;">
        <div style="display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;">
          <span :style="{ color: validationResult.zip_contents.has_database ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
            <FontAwesomeIcon :icon="validationResult.zip_contents.has_database ? 'check-circle' : 'times-circle'" /> 数据库
          </span>
          <span :style="{ color: validationResult.zip_contents.has_filestore ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
            <FontAwesomeIcon :icon="validationResult.zip_contents.has_filestore ? 'check-circle' : 'minus-circle'" /> 附件({{ validationResult.zip_contents.filestore_count || 0 }})
          </span>
          <span :style="{ color: validationResult.zip_contents.has_config ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
            <FontAwesomeIcon :icon="validationResult.zip_contents.has_config ? 'check-circle' : 'minus-circle'" /> 配置
          </span>
          <span :style="{ color: validationResult.zip_contents.has_redis ? 'var(--color-success-500)' : 'var(--color-warning-500)' }">
            <FontAwesomeIcon :icon="validationResult.zip_contents.has_redis ? 'check-circle' : 'minus-circle'" /> Redis
          </span>
        </div>
      </div>
      <div v-if="missingTables.length" class="bk-validate-warn">
        <FontAwesomeIcon icon="exclamation-triangle" /> {{ missingTables.length }} 个表在当前数据库中不存在：{{ missingTables.join(', ') }}
      </div>
      <div v-if="validationResult.checksum_errors?.length" class="bk-validate-warn">
        <FontAwesomeIcon icon="exclamation-triangle" /> {{ validationResult.checksum_errors.join('; ') }}
      </div>
    </div>
    <button class="bk-action-btn bk-action-danger" :disabled="importing" @click="$emit('restore')" :aria-label="importing ? '正在恢复...' : '一键恢复全部数据'">
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
</template>

<script setup lang="ts">
import RestoreProgressBar, { type RestoreResult } from '@/components/backup/RestoreProgressBar.vue'

interface BackupValidationSummary {
  format?: string
  exported_at?: string
  exported_by?: string
  table_count?: number
  total_rows?: number
  checksums_ok?: boolean | null
  remark?: string
  zip_contents?: {
    has_database?: boolean
    has_filestore?: boolean
    filestore_count?: number
    has_config?: boolean
    has_redis?: boolean
  }
  checksum_errors?: string[]
}

defineProps<{
  validationResult: BackupValidationSummary | null
  importing: boolean
  restoreTaskId: string | null
  missingTables: string[]
}>()

defineEmits<{
  (e: 'restore'): void
  (e: 'restore-completed', result: RestoreResult): void
  (e: 'restore-failed', error: string): void
}>()
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }

.bk-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
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

.bk-validate-warn i { margin-right: 4px; }

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
</style>