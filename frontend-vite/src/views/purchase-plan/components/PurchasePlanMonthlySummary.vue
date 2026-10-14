<template>
  <div class="sp-body">
    <div v-if="loading" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="error" class="sp-empty">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败
      <button class="sp-retry-btn" aria-label="重试" @click="emit('refetch')">重试</button>
    </div>
    <div v-else-if="!hasData" class="sp-empty">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />本月暂无数据
    </div>
    <template v-else>
      <div v-if="fetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>

      <FactorySummaryCard v-if="factory === 'all'" :customers="customers" />

      <div class="sp-layout">
        <div class="sp-panel">
          <div class="sp-panel-head">
            <span>SKU 月度统计</span>
            <span class="xs">{{ sortedSkuList.length }} 条{{ custFilter ? ` · ${custFilter}` : '' }}</span>
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
            >{{ c.customer_name }}<span class="sp-chip-n num">{{ fmt(c.plan_qty) }}</span></button>
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
        </div>

        <div class="sp-rail">
          <div class="sp-panel">
            <div class="sp-panel-head">
              <span>客户出货分布</span>
              <span class="xs">本月计划量</span>
            </div>
            <CustomerDistPanel :customers="customers" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 「月度汇总」Tab —— 顶部客户 chips（带计划量）+ SKU 统计表 + 右栏客户分布。
// chips 上原先只有客户名：选定客户后仍要自己回表哥里算这家占多少量。
import { computed } from 'vue'
import SkuSummaryTable from './SkuSummaryTable.vue'
import CustomerDistPanel from './CustomerDistPanel.vue'
import FactorySummaryCard from './FactorySummaryCard.vue'
import type { CustSumItem, SkuRow } from './types'

const props = defineProps<{
  loading: boolean
  error: boolean
  fetching: boolean
  hasData: boolean
  customers: CustSumItem[]
  /** 工厂筛选（'all' 表示全部）；仅「全部」时展示顶部按工厂汇总卡片 */
  factory: string
  custFilter: string
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
  refetch: []
}>()

const totalPlanQty = computed(
  () => props.customers.reduce((n, c) => n + Number(c.plan_qty || 0), 0),
)

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 22px;
}

.sp-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}

@media (max-width: 1180px) {
  .sp-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.sp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 12px 18px 14px;
}

.sp-chip {
  padding: 5px 11px;
  border: 1.5px solid var(--color-border-light, #e2e8f0);
  border-radius: 16px;
  background: white;
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
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
  margin-left: 5px;
  font-weight: 700;
  opacity: 0.68;
}
</style>
