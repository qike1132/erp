<template>
  <div
    v-if="checkResult"
    class="bk-check-result"
    :class="checkResult.failed > 0 ? 'bk-check-warn' : 'bk-check-ok'"
  >
    <FontAwesomeIcon :icon="checkResult.failed > 0 ? 'exclamation-triangle' : 'check-circle'" />
    <span>
      巡检完成：{{ checkResult.passed }} 通过，{{ checkResult.failed }} 失败
      <template v-if="checkResult.latest_backup"> · 最新备份: {{ checkResult.latest_backup }} ({{ formatSize(checkResult.latest_backup_size ?? 0) }})</template>
    </span>
    <button class="bk-check-close" aria-label="操作按钮" @click="$emit('close')"><FontAwesomeIcon icon="times" /></button>
  </div>
</template>

<script setup lang="ts">
export interface IntegrityCheckResult {
  passed: number
  failed: number
  latest_backup?: string
  latest_backup_size?: number
}

defineProps<{
  checkResult: IntegrityCheckResult | null
}>()

defineEmits<{
  (e: 'close'): void
}>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.bk-check-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  margin: 0 20px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
  flex-shrink: 0;
}

.bk-check-ok {
  background: var(--color-success-50);
  color: var(--color-success-700);
  border: 1px solid var(--color-success-200);
}

.bk-check-warn {
  background: var(--color-warning-50);
  color: var(--color-warning-700);
  border: 1px solid var(--color-warning-200);
}

.bk-check-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.bk-check-close:hover {
  opacity: 1;
}
</style>
