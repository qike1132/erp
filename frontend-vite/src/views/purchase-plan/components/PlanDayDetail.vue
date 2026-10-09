<template>
  <div class="sp-detail">
    <div class="sp-detail-head">
      <div class="sp-detail-title">{{ title }}</div>
      <div class="sp-detail-meta">
        <span>合计 <b class="num">{{ fmt(totalQty) }}</b> 件</span>
        <i aria-hidden="true" />
        <span><b>{{ customerCount }}</b> 家客户</span>
        <i aria-hidden="true" />
        <span><b>{{ productCount }}</b> 个产品</span>
      </div>
    </div>

    <div class="sp-detail-groups">
      <div v-for="g in groups" :key="g.customer" class="sp-group">
        <div class="sp-group-head">
          <span class="sp-group-name" :title="g.customer">{{ g.customer }}</span>
          <span class="sp-group-qty num">{{ fmt(g.qty) }}</span>
        </div>
        <ul class="sp-prod-list">
          <li v-for="p in g.products" :key="p.product" class="sp-prod-row">
            <i
              v-if="factory === 'all'"
              class="sp-prod-fdot"
              :class="`fd-${factoryTone(p.factory)}`"
              :title="p.factory || '未标注'"
              aria-hidden="true"
            />
            <span class="sp-prod-name" :title="p.product">{{ p.product }}</span>
            <span class="sp-prod-dots" aria-hidden="true" />
            <span class="sp-prod-qty num">{{ fmt(p.qty) }}</span>
            <span class="sp-prod-st" :class="statusOf(p.status).cls">{{ statusOf(p.status).lbl }}</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 右栏的当日明细 —— 客户分组 + 全部产品，不截断，超出滚动。
// 条目按产品行展示的是「该客户该产品当日」的出货状态，与后端 getShipmentStatus 同口径。
import { factoryTone } from './factoryMeta'
import type { PlanDayCustomerGroup } from './types'

defineProps<{
  title: string
  groups: PlanDayCustomerGroup[]
  totalQty: number
  customerCount: number
  productCount: number
  /** 当前工厂筛选；'all' 时每个产品前显示工厂色点 */
  factory: string
}>()

const PENDING = { cls: 'st-wait', lbl: '待生产' }

const STATUS: Record<string, { cls: string; lbl: string }> = {
  completed: { cls: 'st-ok', lbl: '已生产' },
  partial: { cls: 'st-part', lbl: '部分生产' },
  pending: PENDING,
}

function statusOf(s: string): { cls: string; lbl: string } {
  return STATUS[s] ?? PENDING
}

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}
</script>

<style scoped lang="scss">
.sp-detail {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sp-detail-head {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-detail-title {
  font-size: 14px;
  font-weight: 800;
  color: var(--color-heading);
}

.sp-detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: 11px;
  color: var(--color-text-muted, #8c96ad);
}

.sp-detail-meta i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
}

.sp-detail-meta b {
  font-weight: 800;
  color: var(--color-text-secondary, #5a6b8c);
}

.sp-detail-groups {
  max-height: 396px;
  overflow-y: auto;
}

.sp-group {
  padding: 10px 16px 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-group:last-child {
  border-bottom: none;
}

.sp-group-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.sp-group-name {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-weight: 800;
  color: var(--color-primary-700);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sp-group-qty {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 800;
  color: var(--color-text-secondary, #5a6b8c);
}

.sp-prod-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* 名称 … 数量：点线引导视线对齐两侧，避免长名单读错行 */
.sp-prod-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 2px 0;
  font-size: 11.5px;
}

.sp-prod-name {
  flex: 0 1 auto;
  min-width: 0;
  color: var(--color-text-secondary, #475569);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 工厂色点（仅「全部」视图）：东莞主色 / 湖北紫 / 其余中性 */
.sp-prod-fdot {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  align-self: center;
}

.fd-dg { background: var(--color-primary-500, #5b8def); }
.fd-hb { background: var(--color-purple-500, #8b5cf6); }
.fd-other { background: var(--color-slate-300, #cbd5e1); }

.sp-prod-dots {
  flex: 1 1 auto;
  min-width: 8px;
  align-self: center;
  border-bottom: 1px dotted var(--color-border, #e4e7ed);
}

.sp-prod-qty {
  flex-shrink: 0;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-prod-st {
  flex-shrink: 0;
  width: 30px;
  text-align: right;
  font-size: 10px;
  font-weight: 600;
}

.st-ok { color: var(--color-success-600); }
.st-part { color: var(--color-warning-600); }
.st-wait { color: var(--color-warning-600); }
</style>
