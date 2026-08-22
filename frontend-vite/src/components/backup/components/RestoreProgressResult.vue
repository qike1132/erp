<template>
  <div class="rp-result-summary" :class="resultSummaryClass">
    <FontAwesomeIcon :icon="resultIcon" aria-hidden="true" />
    {{ resultText }}
    <span v-if="result.total_inserted && !hasDbError"> · {{ result.total_inserted }} 条记录</span>
    <span v-if="(result.format === 'zip' || result.database) && !hasDbError"> · ZIP完整备份</span>
  </div>
</template>

<script setup lang="ts">
import type { RestoreResult } from '../composables/useRestorePolling'

defineProps<{
  result: RestoreResult
  hasDbError: boolean
  resultSummaryClass: string
  resultIcon: string
  resultText: string
}>()
</script>

<style scoped>
.rp-result-summary {
  margin-top: 10px;
  padding: 8px 12px;
  background: var(--color-success-50, #f0fdf4);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-success-700, #15803d);
  font-weight: 500;
}

.rp-result-failed {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-700, #b91c1c);
}

.rp-result-warning {
  background: var(--color-warning-50, #fefce8);
  color: var(--color-warning-700, #a16207);
}
</style>