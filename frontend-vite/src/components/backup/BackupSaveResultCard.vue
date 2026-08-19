<template>
  <div class="bk-section">
    <div class="bk-result-card bk-result-success">
      <div class="bk-result-header">
        <FontAwesomeIcon icon="check-circle" /> 备份已保存
      </div>
      <div class="bk-result-stats">
        <span>文件: <b>{{ result.filename }}</b></span>
        <span>{{ formatSize(result.size) }}</span>
        <span>{{ result.format === 'zip' ? 'ZIP' : 'JSON' }}</span>
        <span>{{ result.table_count }} 表 / {{ result.total_rows }} 条</span>
      </div>
      <div v-if="result.format === 'zip' && result.includes" class="bk-backup-includes" style="margin-top: 8px;">
        <span v-if="result.includes.filestore_count" class="bk-badge"><FontAwesomeIcon icon="paperclip" /> {{ result.includes.filestore_count }} 附件</span>
        <span v-if="result.includes.config_files?.length" class="bk-badge"><FontAwesomeIcon icon="cog" /> {{ result.includes.config_files.length }} 配置</span>
        <span v-if="result.includes.redis_rdb" class="bk-badge"><FontAwesomeIcon icon="bolt" /> Redis</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
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

defineProps<{ result: BackupSaveResult }>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.bk-section { margin-bottom: 20px; }
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
.bk-result-success .bk-result-header i { color: var(--color-success-500); }
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