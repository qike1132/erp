<template>
  <TabsTrigger
    :value="value"
    :class="[
      'ui-tab-btn',
      active ? 'active' : '',
    ]"
  >
    <slot />
    <span
      v-if="badge !== undefined"
      :class="[
        'ui-tab-badge',
        active ? 'ui-tab-badge-active' : '',
      ]"
    >
      {{ badge }}
    </span>
  </TabsTrigger>
</template>

<script setup lang="ts">
import { TabsTrigger } from 'reka-ui'

defineProps<{
  value: string
  active?: boolean
  badge?: number
}>()
</script>

<style scoped>
.ui-tab-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
}
.ui-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.ui-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.ui-tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 700;
  background: var(--color-border-light);
  color: var(--color-text-secondary);
}
.ui-tab-badge-active {
  background: var(--color-primary-500);
  color: white;
}
</style>
