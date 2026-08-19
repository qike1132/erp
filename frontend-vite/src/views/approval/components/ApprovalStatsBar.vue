<template>
  <div v-if="stats" class="ap-stats">
    <div class="ap-stat-card ap-stat-pending">
      <div class="ap-stat-icon"><FontAwesomeIcon icon="clock" aria-hidden="true" /></div>
      <div class="ap-stat-value">{{ stats.pending }}</div>
      <div class="ap-stat-label">待审批</div>
    </div>
    <div class="ap-stat-card ap-stat-approved">
      <div class="ap-stat-icon"><FontAwesomeIcon icon="check-circle" aria-hidden="true" /></div>
      <div class="ap-stat-value">{{ stats.approved }}</div>
      <div class="ap-stat-label">已通过</div>
    </div>
    <div class="ap-stat-card ap-stat-rejected">
      <div class="ap-stat-icon"><FontAwesomeIcon icon="times-circle" aria-hidden="true" /></div>
      <div class="ap-stat-value">{{ stats.rejected }}</div>
      <div class="ap-stat-label">已驳回</div>
    </div>
    <div class="ap-stat-card ap-stat-total">
      <div class="ap-stat-icon"><FontAwesomeIcon icon="list-check" aria-hidden="true" /></div>
      <div class="ap-stat-value">{{ stats.total }}</div>
      <div class="ap-stat-label">合计</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ApprovalStats } from '../composables/useApproval'

defineProps<{ stats: ApprovalStats | null }>()
</script>

<style scoped>
.ap-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ap-stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px;
  border-radius: 13px;
  transition: transform 0.3s ease;
}
.ap-stat-card:hover {
  transform: translateY(-1px);
}
.ap-stat-icon {
  font-size: 18px;
  margin-bottom: 4px;
}
.ap-stat-value {
  font-size: 28px;
  font-weight: 800;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.ap-stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.ap-stat-pending {
  background: var(--color-warning-50);
  border: 1px solid var(--color-warning-200);
}
.ap-stat-pending .ap-stat-icon, .ap-stat-pending .ap-stat-value { color: var(--color-warning-600); }
.ap-stat-approved {
  background: var(--color-success-50);
  border: 1px solid var(--color-success-200);
}
.ap-stat-approved .ap-stat-icon, .ap-stat-approved .ap-stat-value { color: var(--color-success-600); }
.ap-stat-rejected {
  background: var(--color-danger-50);
  border: 1px solid var(--color-danger-200);
}
.ap-stat-rejected .ap-stat-icon, .ap-stat-rejected .ap-stat-value { color: var(--color-danger-600); }
.ap-stat-total {
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-200);
}
.ap-stat-total .ap-stat-icon, .ap-stat-total .ap-stat-value { color: var(--color-primary-600); }
</style>