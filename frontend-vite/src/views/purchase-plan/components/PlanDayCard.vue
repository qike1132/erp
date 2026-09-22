<template>
  <div
    class="sp-day-card"
    :class="cardClass"
    role="button"
    tabindex="0"
    :aria-label="ariaLabel"
    @click="emit('select', card.date)"
    @keydown.enter.prevent="emit('select', card.date)"
    @keydown.space.prevent="emit('select', card.date)"
  >
    <div class="sp-day-head">
      <span class="sp-day-date">{{ card.label }}</span>
      <span v-if="card.status" class="st" :class="card.status.cls">{{ card.status.lbl }}</span>
      <span class="sp-day-total num">{{ card.totalQty }}<small>件</small></span>
    </div>

    <div class="sp-day-meta">
      <span>{{ card.customerCount }} 家客户</span>
      <i class="dot" aria-hidden="true" />
      <span>{{ card.planCount }} 个产品</span>
    </div>

    <div class="sp-day-groups">
      <div v-for="g in card.groups" :key="g.customer" class="sp-cust-group">
        <div class="sp-cust-head">
          <span class="sp-cust-name" :title="g.customer">{{ g.customer }}</span>
          <span class="sp-cust-qty num">{{ g.qty }}</span>
        </div>
        <ul class="sp-prod-list">
          <li v-for="p in g.products" :key="p.product" class="sp-prod-row">
            <span class="sp-prod-name" :title="p.product">{{ p.product }}</span>
            <span class="sp-prod-dots" aria-hidden="true" />
            <span class="sp-prod-qty num">{{ p.qty }}</span>
          </li>
        </ul>
      </div>
      <div v-if="card.extra" class="sp-more">{{ moreLabel }}</div>
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

/** 卡片整体是一条可点击/可回车触发的操作，需要一句话说明其用途 */
const ariaLabel = computed(() => {
  const c = props.card;
  return `${c.label}，共 ${c.totalQty} 件，${c.customerCount} 家客户 ${c.planCount} 个产品，查看当日明细`;
});

/** 折叠提示：客户被整组藏掉时必须点名，否则「还有 N 个产品」会掩盖客户数缺口 */
const moreLabel = computed(() => {
  const { extra, extraCustomers } = props.card;
  const custPart = extraCustomers ? `${extraCustomers} 家客户 / ` : '';
  return `还有 ${custPart}${extra} 个产品，点击查看全部`;
});
</script>

<style scoped lang="scss">
/* 排产日历：单张计划日卡片
   状态用左侧色条表达而非整卡染色 —— 整卡渐变会把正文压在同色背景上降低可读性，
   且多张同状态卡片并排时满屏色块、彼此无法区分。 */
.sp-day-card {
  position: relative;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-md, 14px);
  padding: 13px 15px 13px 19px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: box-shadow 0.25s ease, border-color 0.25s ease, transform 0.25s ease;
}
.sp-day-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-border, #e4e7ed);
}
.sp-day-card:hover {
  box-shadow: 0 4px 16px rgba(176, 224, 230, 0.35);
  transform: translateY(-1px);
}
.sp-day-card:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

/* 未命中搜索：整体淡化但仍可读 */
.sp-day-dim { opacity: 0.4; }

.sp-day-danger::before { background: var(--color-danger-500); }
.sp-day-due::before { background: var(--color-warning-500); }
.sp-day-done::before { background: var(--color-success-500); }

.sp-day-danger { border-color: var(--color-danger-200); }
.sp-day-due { border-color: var(--color-warning-200); }
.sp-day-done { border-color: var(--color-success-200); }

.sp-day-selected {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

/* ---- 头部：日期 · 状态 · 总量 ---- */
.sp-day-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.sp-day-date {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-heading);
  letter-spacing: -0.01em;
}
.sp-day-total {
  margin-left: auto;
  font-size: 19px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.sp-day-total small {
  font-size: 10px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-left: 1px;
}

.sp-day-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: -4px;
}
.sp-day-meta .dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
}

/* ---- 客户分组 ---- */
.sp-day-groups {
  display: flex;
  flex-direction: column;
  gap: 9px;
  border-top: 1px solid var(--color-border-light);
  padding-top: 10px;
}

.sp-cust-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 3px;
}
.sp-cust-name {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-primary-700);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-cust-qty {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.sp-prod-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 产品行：名称 … 数量，用点线引导视线对齐两侧，避免长名单读错行 */
.sp-prod-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 1px 0;
}
.sp-prod-name {
  flex: 0 1 auto;
  min-width: 0;
  font-size: 12px;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sp-prod-dots {
  flex: 1 1 auto;
  min-width: 8px;
  align-self: center;
  border-bottom: 1px dotted var(--color-border);
  opacity: 0.9;
}
.sp-prod-qty {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
}

.sp-more {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary-600);
  padding-top: 1px;
}

/* ---- 状态标签 ---- */
.sp-day-card .st {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 5px;
  white-space: nowrap;
  line-height: 1.4;
}
.st-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.st-a { background: var(--color-warning-100); color: var(--color-warning-700); }
.st-g { background: var(--color-success-100); color: var(--color-success-700); }
</style>
