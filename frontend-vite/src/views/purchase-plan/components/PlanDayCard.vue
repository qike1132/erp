<template>
  <div
    class="sp-day-card"
    :class="cardClass"
    @click="emit('select', card.date)"
  >
    <div class="sp-day-head">
      <span class="sp-day-date">{{ card.label }}</span>
      <span v-if="card.status" class="st" :class="card.status.cls">{{ card.status.lbl }}</span>
      <span class="sp-day-total num">{{ card.totalQty }}<small>件</small></span>
    </div>
    <div class="sp-day-sub">{{ card.customerCount }} 家客户 · {{ card.planCount }} 条计划</div>
    <div class="sp-day-items">
      <div v-for="it in card.items" :key="it.customer + '|' + it.product" class="sp-plan-row">
        <div class="sp-plan-txt">
          <span class="sp-plan-cu">{{ it.customer }}</span>
          <span class="sp-plan-pd">{{ it.product }}</span>
        </div>
        <span class="sp-plan-q num">{{ it.qty }}</span>
      </div>
      <div v-if="card.extra" class="sp-plan-more">还有 {{ card.extra }} 条，点击查看全部</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { PlanDayCard } from './types';

const props = defineProps<{
  card: PlanDayCard;
  /** 当前选中日期，用于高亮 */
  sel: string;
}>();

const emit = defineEmits<{
  select: [date: string];
}>();

/** 状态与选中态 → CSS 类；仅做样式映射，不含业务判断 */
const cardClass = computed<string[]>(() => {
  const cls: string[] = [];
  if (!props.card.match) cls.push('sp-day-dim');
  if (props.card.status?.cls === 'st-r') cls.push('sp-day-danger');
  else if (props.card.status?.cls === 'st-a') cls.push('sp-day-due');
  else if (props.card.status?.cls === 'st-g') cls.push('sp-day-done');
  if (props.sel === props.card.date) cls.push('sp-day-selected');
  return cls;
});
</script>

<style scoped lang="scss">
/* 排产日历：单张计划日卡片 */
.sp-day-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  padding: 12px 14px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.sp-day-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.sp-day-dim { opacity: 0.35; }
.sp-day-danger {
  border: 1.5px solid var(--color-danger-500);
  background: linear-gradient(180deg, #fff, var(--color-danger-100));
}
.sp-day-due {
  border: 1.5px solid var(--color-warning-500);
  background: linear-gradient(180deg, #fff, var(--color-warning-100));
}
.sp-day-done {
  border: 1.5px solid var(--color-success-500);
  background: linear-gradient(180deg, #fff, var(--color-success-100));
}
.sp-day-selected {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.sp-day-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sp-day-date {
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
}
.sp-day-total {
  margin-left: auto;
  font-size: 17px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
}
.sp-day-total small { font-size: 10px; color: var(--color-muted, #8c96ad); font-weight: 600; }
.sp-day-sub {
  font-size: 11px;
  color: var(--color-muted, #8c96ad);
}

.sp-day-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
  padding-top: 8px;
}
.sp-plan-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.sp-plan-txt {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.sp-plan-cu {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-2, #5a6b8c);
  word-break: break-word;
}
.sp-plan-pd {
  font-size: 12px;
  color: var(--color-text-3, var(--color-muted, #8c96ad));
  word-break: break-word;
}
.sp-plan-q {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
}
.sp-plan-more {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary-600);
  padding-top: 2px;
}

.sp-day-card .st {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 5px;
  width: fit-content;
  white-space: nowrap;
}
.st-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.st-a { background: var(--color-warning-100); color: var(--color-warning-700); }
.st-g { background: var(--color-success-100); color: var(--color-success-700); }
</style>
