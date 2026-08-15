<template>
  <div class="sp-body">
    <div v-if="isLoading && !d" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="isError" class="sp-empty"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败 <button class="sp-retry-btn" @click="emit('refetch')">重试</button></div>
    <div v-else-if="!rows.length" class="sp-empty"><FontAwesomeIcon icon="inbox" aria-hidden="true" />本月暂无出货计划</div>
    <template v-else>
    <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>
    <div>
      <div class="sp-day-grid">
        <div
          v-for="(r, idx) in filtered"
          :key="r.date"
          class="sp-day-card"
          :class="{
            'sp-day-selected': sel === r.date,
          }"
          @click="emit('update:sel', sel === r.date ? '' : r.date)"
        >
          <div class="sp-day-header">
            <span class="sp-day-badge">{{ r._fullDate }}：{{ fmtQty(r.totalQty) }}</span>
            <span v-if="r._pendingCount > 0" class="sp-day-alert" :class="getAlertClass(r.date)">{{ getAlertLabel(r.date) }}</span>
            <span v-else-if="r._shippedPct === 100" class="sp-day-alert sp-day-done"><FontAwesomeIcon icon="check" aria-hidden="true" /> 完成</span>
          </div>

          <div class="sp-day-body">
            <span v-for="(cn, i) in r.customerNames.slice(0, 5)" :key="cn" class="sp-day-customer-tag">
              {{ cn }}
            </span>
            <span v-if="r.customerNames.length > 5" class="sp-day-more-tag">
              +{{ r.customerNames.length - 5 }}家客户
            </span>            </div>
      </div>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 每日计划 Tab（从 PurchasePlanView.vue 抽出，模板原样搬移）
import type { Row } from './types';

defineProps<{
  isLoading: boolean;
  d: Record<string, unknown> | undefined;
  isError: boolean;
  isFetching: boolean;
  rows: Row[];
  filtered: Row[];
  sel: string;
}>();

const emit = defineEmits<{
  'update:sel': [value: string];
  refetch: [];
}>();

function fmtQty(n: number): string {
  return String(n);
}

function getDaysDiff(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr + 'T00:00:00');
  return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function getAlertClass(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return 'sp-day-overdue';
  if (diff <= 3) return 'sp-day-due-soon';
  return '';
}

function getAlertLabel(dateStr: string): string {
  const diff = getDaysDiff(dateStr);
  if (diff < 0) return '延期 ' + Math.abs(diff) + ' 天';
  if (diff === 0) return '今日出货';
  if (diff <= 3) return '临期 ' + diff + ' 天';
  return '';
}
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;
.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-day-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.sp-day-card {
  padding: 18px;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
  position: relative;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 260px;
  overflow: hidden;
}

.sp-day-card:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}

.sp-day-selected {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

.sp-day-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 0 8px;
  margin-top: -10px;
  flex-shrink: 0;
}

.sp-day-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
  border-radius: 6px;
  white-space: nowrap;
}

.sp-day-alert {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.sp-day-due-soon {
  background: var(--color-warning-100);
  color: var(--color-warning-700);
}

.sp-day-overdue {
  background: var(--color-danger-100);
  color: var(--color-danger-700);
}

.sp-day-done {
  background: var(--color-success-100);
  color: var(--color-success-700);
}

.sp-day-customer-tag {
  display: block;
  font-size: 14px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1.2;
}

.sp-day-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
  min-height: 0;
  flex: 1;
}

.sp-day-more-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  padding: 3px 10px;
  border-radius: 10px;
  cursor: pointer;
}
</style>
