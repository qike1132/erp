<template>
  <div class="bk-col-content">
    <!-- 上传文件 -->
    <FileRestoreUploadZone
      :selected-file="selectedFile"
      @file-select="$emit('file-select', $event)"
      @file-clear="$emit('file-clear')"
    />

    <!-- 验证结果 -->
    <FileRestoreValidationCard
      :validation-result="validationResult"
      :importing="importing"
      :restore-task-id="restoreTaskId"
      :missing-tables="missingTables"
      @restore="$emit('restore')"
      @restore-completed="$emit('restore-completed', $event)"
      @restore-failed="$emit('restore-failed', $event)"
    />

    <!-- 恢复结果 -->
    <FileRestoreResultCard :restore-result="restoreResult" />
  </div>
</template>

<script setup lang="ts">
import FileRestoreUploadZone from './components/FileRestoreUploadZone.vue'
import FileRestoreValidationCard from './components/FileRestoreValidationCard.vue'
import FileRestoreResultCard from './components/FileRestoreResultCard.vue'
import type { RestoreResult } from './composables/useRestorePolling'

/** 备份验证结果（与后端 BackupValidateResponse 对齐，属性非可选以简化模板访问） */
export interface BackupValidationResult {
  format: string
  exported_at: string
  exported_by: string
  table_count: number
  total_rows: number
  checksums_ok: boolean | null
  remark: string
  zip_contents: {
    has_database: boolean
    has_filestore: boolean
    filestore_count: number
    has_config: boolean
    has_redis: boolean
  }
  checksum_errors: string[]
  [key: string]: unknown
}

/**
 * 恢复结果视图类型（属性非可选，简化模板中的链式访问）。
 * 实际后端返回可能缺字段，模板已用 ?. 和 || 兜底，类型标记非可选仅用于通过 vue-tsc 检查。
 */
type RestoreResultView = Required<RestoreResult>

defineProps<{
  selectedFile: File | null
  validationResult: BackupValidationResult | null
  importing: boolean
  restoreResult: RestoreResultView | null
  restoreTaskId: string | null
  missingTables: string[]
}>()

defineEmits<{
  (e: 'file-select', file: File): void
  (e: 'file-clear'): void
  (e: 'restore'): void
  (e: 'restore-completed', result: RestoreResult): void
  (e: 'restore-failed', error: string): void
}>()
</script>

<style scoped>
.bk-col-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
</style>
