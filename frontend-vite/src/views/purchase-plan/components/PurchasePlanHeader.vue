<template>
  <div class="sp-head">
    <div class="sp-head-row1">
      <!-- 工厂 Tab 左置：与视图 Tab 同属「看哪些数据」的切换，排在一起比藏在第二行更直观 -->
      <PurchasePlanFactoryFilter v-model="factory" :factories="factories" :totals="factoryTotals" />
      <div class="sp-tab-group" role="tablist">
        <button
          role="tab"
          :aria-selected="viewTab === 'daily'"
          :class="['sp-tab', { 'sp-tab-active': viewTab === 'daily' }]"
          @click="viewTab = 'daily'"
        >排产日历</button>
        <button
          role="tab"
          :aria-selected="viewTab === 'summary'"
          :class="['sp-tab', { 'sp-tab-active': viewTab === 'summary' }]"
          @click="viewTab = 'summary'"
        >月度汇总</button>
      </div>
      <PurchasePlanToolbar
        v-model:global-kw="globalKw"
        :view-tab="viewTab"
        @export="emit('export')"
        @create="emit('create')"
      />
    </div>

    <!-- 第二行：月份上下文 + 该月汇总。
         切月作用于整页（KPI 与两个 Tab 都跟着变），所以与 KPI 同行。 -->
    <div class="sp-head-row2">
      <PurchasePlanMonthNav :y="y" :m="m" @prev="emit('prev')" @next="emit('next')" @reset="emit('reset')" />
      <PurchasePlanKpiStrip v-bind="kpi" />
    </div>
  </div>
</template>

<script setup lang="ts">
// 采购计划页头部两行 —— 从 PurchasePlanView.vue 抽出，使视图回到 400 行门禁之内。
// 只负责布局与转发：数据由父级传入，交互一律上抛事件，判定/聚合仍在原处。
import PurchasePlanFactoryFilter from './PurchasePlanFactoryFilter.vue'
import PurchasePlanToolbar from './PurchasePlanToolbar.vue'
import PurchasePlanMonthNav from './PurchasePlanMonthNav.vue'
import PurchasePlanKpiStrip from './PurchasePlanKpiStrip.vue'

defineProps<{
  y: number
  m: number
  factories: string[]
  factoryTotals: Record<string, number>
  kpi: {
    planQty: number
    producedQty: number
    remainQty: number
    pct: number
    planDays: number
    riskDays: number
    riskOverdue: number
    riskExpiring: number
    riskQty: number
  }
}>()

const viewTab = defineModel<'daily' | 'summary'>('viewTab', { required: true })
const factory = defineModel<string>('factory', { required: true })
const globalKw = defineModel<string>('globalKw', { required: true })

const emit = defineEmits<{ prev: []; next: []; reset: []; export: []; create: [] }>()
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

/* 头部两行：第一行「看哪个工厂/Tab + 做什么」，第二行「看哪个月 + 这个月怎么样」。 */
.sp-head {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.sp-head-row1 {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.sp-head-row2 {
  display: flex;
  align-items: stretch;
  gap: 16px;
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .sp-head-row2 {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
