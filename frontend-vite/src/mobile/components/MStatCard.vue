<template>
  <div :class="['m-stat-card', variant]">
    <div class="m-stat-icon-wrap" :style="{ background: iconBg }">
      <slot name="icon" />
    </div>
    <div class="m-stat-body">
      <div class="m-stat-value">{{ displayValue }}</div>
      <div class="m-stat-label">{{ label }}</div>
    </div>
    <div v-if="trend !== undefined" :class="['m-stat-trend', { up: trend > 0, down: trend < 0 }]">
      <svg v-if="trend > 0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="12" height="12"><polyline points="18 15 12 9 6 15" /></svg>
      <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="12" height="12"><polyline points="6 9 12 15 18 9" /></svg>
      {{ Math.abs(trend) }}%
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: number | string
  label: string
  trend?: number
  variant?: 'default' | 'accent' | 'success' | 'warning'
  iconBg?: string
}>()

const displayValue = computed(() => {
  if (typeof props.value === 'number') {
    return props.value.toLocaleString('zh-CN')
  }
  return props.value
})
</script>

<style scoped>
.m-stat-card {
  display: flex;
  align-items: center;
  gap: var(--m-gap-sm);
  padding: var(--m-gap-md);
  background: var(--m-bg-card);
  border-radius: var(--m-radius-md);
  box-shadow: var(--m-shadow-card);
}

.m-stat-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.m-stat-body {
  flex: 1;
  min-width: 0;
}

.m-stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--m-text-primary);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.m-stat-label {
  font-size: 13px;
  color: var(--m-text-secondary);
  margin-top: 2px;
  line-height: 1.2;
}

.m-stat-trend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 600;
  color: var(--m-text-tertiary);
}

.m-stat-trend.up {
  color: var(--m-accent-emerald);
}

.m-stat-trend.down {
  color: var(--m-accent-rose);
}
</style>
