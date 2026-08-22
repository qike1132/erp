<template>
  <div class="rp-header">
    <div class="rp-header-left">
      <div class="rp-icon" :class="iconClass">
        <FontAwesomeIcon :icon="iconName.replace(' fa-spin', '')" :spin="!!iconClass['rp-icon-running']" aria-hidden="true" />
      </div>
      <div class="rp-header-text">
        <div class="rp-title">{{ statusTitle }}</div>
        <div v-if="phaseLabel" class="rp-phase">{{ phaseLabel }}</div>
      </div>
    </div>
    <div class="rp-percent" :class="percentClass">{{ displayPercent }}%</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  statusTitle: string
  phaseLabel: string
  displayPercent: number
  iconClass: Record<string, boolean>
  iconName: string
  percentClass: Record<string, boolean>
}>()
</script>

<style scoped>
.rp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.rp-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.rp-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.rp-icon-pending {
  background: var(--color-primary-100, #dbeafe);
  color: var(--color-primary-600, #2563eb);
}

.rp-icon-running {
  background: var(--color-primary-100, #dbeafe);
  color: var(--color-primary-600, #2563eb);
}

.rp-icon-completed {
  background: var(--color-success-100, #dcfce7);
  color: var(--color-success-600, #16a34a);
}

.rp-icon-warning {
  background: var(--color-warning-100, #fef9c3);
  color: var(--color-warning-600, #ca8a04);
}

.rp-icon-failed {
  background: var(--color-danger-100, #fee2e2);
  color: var(--color-danger-600, #dc2626);
}

.rp-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text, #1e293b);
}

.rp-phase {
  font-size: 12px;
  color: var(--color-text-secondary, #64748b);
  margin-top: 2px;
}

.rp-percent {
  font-size: 28px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.rp-percent-primary {
  color: var(--color-primary-600, #2563eb);
}

.rp-percent-success {
  color: var(--color-success-600, #16a34a);
}

.rp-percent-warning {
  color: var(--color-warning-600, #ca8a04);
}

.rp-percent-danger {
  color: var(--color-danger-600, #dc2626);
}
</style>