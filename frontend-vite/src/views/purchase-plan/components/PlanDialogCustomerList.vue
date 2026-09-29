<template>
  <div class="sp-modal-sidebar">
    <VirtualList
      :items="customerList"
      :item-height="72"
      :container-height="460"
      :item-key="(c) => c.name"
    >
      <template #default="{ item: entry }">
        <div
          class="sp-customer-item"
          :class="{ 'sp-customer-selected': selected === entry.name }"
          @click="$emit('select', entry.name)"
        >
          <div class="sp-customer-row">
            <span class="sp-customer-name">{{ entry.name }}</span>
            <span class="sp-customer-badge">{{ entry.plans.length }}</span>
          </div>
          <div class="sp-customer-summary">
            <span class="sp-customer-summary-item"><b>{{ entry.plans.reduce((s: number, p: Plan) => s + Number(p.quantity || 0), 0) }}</b> 计划</span>
            <span class="sp-customer-summary-item sp-customer-summary-shipped"><b>{{ entry.plans.reduce((s: number, p: Plan) => s + Number(p.produced_qty || 0), 0) }}</b> 已生产</span>
            <span class="sp-customer-summary-item sp-customer-summary-pending"><b>{{ entry.plans.reduce((s: number, p: Plan) => s + Number(p.remaining_qty || 0), 0) }}</b> 待生产</span>
          </div>
        </div>
      </template>
    </VirtualList>
  </div>
</template>

<script setup lang="ts">
import VirtualList from '@/components/ui/VirtualList.vue';
import type { Plan } from './types';

defineProps<{
  customerList: { name: string; plans: Plan[] }[];
  selected: string;
}>();

defineEmits<{ select: [name: string] }>();
</script>

<style scoped>
.sp-modal-sidebar {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--color-border-light);
  padding-right: 20px;
}
.sp-customer-item {
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  background: white;
  cursor: pointer;
}
.sp-customer-item:hover {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}
.sp-customer-selected {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}
.sp-customer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sp-customer-summary {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}
.sp-customer-summary-item {
  font-size: 12px;
  color: var(--color-text-muted);
}
.sp-customer-summary-item b {
  font-weight: 700;
  color: var(--color-text);
  margin-right: 2px;
}
.sp-customer-summary-shipped b { color: var(--color-success-600); }
.sp-customer-summary-pending b { color: var(--color-warning-600); }
.sp-customer-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.sp-customer-badge {
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-size: 11px;
  font-weight: 600;
}
</style>