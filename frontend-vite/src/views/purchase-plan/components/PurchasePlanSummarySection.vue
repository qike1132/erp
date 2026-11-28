<template>
  <div class="sp-sec-head">
    <span>本月客户</span>
    <span class="xs">点客户筛选 SKU 表</span>
  </div>
  <div class="sp-chips">
    <button
      :class="['sp-chip', { 'sp-chip-active': !custFilter }]"
      @click="emit('update:custFilter', '')"
    >全部<span class="sp-chip-n num">{{ fmt(totalPlanQty) }}</span></button>
    <button
      v-for="c in customers"
      :key="c.customer_id"
      :class="['sp-chip', { 'sp-chip-active': custFilter === c.customer_name }]"
      :title="c.customer_name"
      @click="emit('update:custFilter', custFilter === c.customer_name ? '' : c.customer_name)"
    ><i class="sp-chip-dot" :style="{ background: custColor(c.customer_name) }" />{{ c.customer_name }}<span class="sp-chip-n num">{{ fmt(c.plan_qty) }}</span></button>
  </div>

  <div class="sp-sec-head">
    <span>SKU 月度统计</span>
    <span class="xs">{{ sortedSkuList.length }} 条{{ custFilter ? ` · ${custFilter}` : '' }}</span>
    <button class="sp-export-sku" aria-label="导出SKU" @click="emit('export-sku')">导出SKU</button>
  </div>
  <SkuSummaryTable
    :rows="paginatedSkuList"
    :sort-field="skuSortField"
    :sort-dir="skuSortDir"
    :page="skuPage"
    :total-pages="skuTotalPages"
    :total-items="sortedSkuList.length"
    @toggle-sort="emit('toggle-sku-sort', $event)"
    @open-detail="emit('open-sku-detail', $event)"
    @update:page="emit('update:skuPage', $event)"
  />
</template>

<script setup lang="ts">
// 方案B 单视图左列下部的「月度汇总区」——客户 chips（筛选 SKU 表）+ SKU 月度统计表。
// 从 PurchasePlanBoard 拆出以满足「前端巨型 Vue 组件 ≤400 行」门禁；
// 只做渲染与事件上抛，筛选/排序/分页仍由 useSkuSummary 掌管。
import { computed } from 'vue'
import SkuSummaryTable from './SkuSummaryTable.vue'
import type { CustSumItem, SkuRow } from './types'
import { formatNumber as fmt } from '@/utils/format' // L-15（2026-11-21 审计）：删除 8 处各自为政的本地 fmt，统一千分位口径

const props = defineProps<{
  customers: CustSumItem[]
  custFilter: string
  /** 客户 → 展示色（与月历格子、日明细三处同源） */
  custColors?: Record<string, string>
  sortedSkuList: SkuRow[]
  paginatedSkuList: SkuRow[]
  skuPage: number
  skuTotalPages: number
  skuSortField: string
  skuSortDir: 'asc' | 'desc'
}>()

const emit = defineEmits<{
  'update:custFilter': [value: string]
  'update:skuPage': [value: number]
  'toggle-sku-sort': [field: string]
  'open-sku-detail': [payload: { barcode: string; name: string; customer: string }]
  'export-sku': []
}>()

const totalPlanQty = computed(
  () => props.customers.reduce((n, c) => n + Number(c.plan_qty || 0), 0),
)

function custColor(name: string): string {
  return props.custColors?.[name] ?? 'var(--color-slate-400, #94a3b8)'
}
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

/* 区块小标题：客户 chips 与 SKU 表各自的行头 */
.sp-sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 18px 10px;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 14px;
  font-weight: 800;
  color: var(--color-heading);
}

.sp-sec-head .xs {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted, #8c96ad);
}

.sp-export-sku {
  margin-left: auto;
  padding: 4px 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 0;
  background: white;
  font-family: inherit;
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-primary-600);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.sp-export-sku:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
}

.sp-export-sku:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.sp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 18px 12px;
}

.sp-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 1.5px solid var(--color-border-light, #e2e8f0);
  border-radius: 0;
  background: white;
  font-family: inherit;
  font-size: var(--fs-caption);
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.sp-chip-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sp-chip:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-chip-active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-chip-n {
  font-weight: 700;
  opacity: 0.68;
}
</style>
