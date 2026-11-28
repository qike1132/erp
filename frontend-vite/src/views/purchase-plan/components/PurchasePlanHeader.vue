<template>
  <div class="sp-head">
    <div class="sp-head-row1">
      <!-- 工厂 Tab 左置：限定「看哪些数据」的维度（方案B 合并两 Tab 后是头部唯一 Tab 组） -->
      <PurchasePlanFactoryFilter v-model="factory" :factories="factories" :totals="factoryTotals" />
      <PurchasePlanToolbar
        v-model:global-kw="globalKw"
        :can-manage="canManage"
        @export="emit('export')"
        @create="emit('create')"
      />
    </div>

    <!-- 第二行：月份上下文 + 该月汇总。
         切月作用于整页（信息条与月历都跟着变），所以与信息条同行。 -->
    <div class="sp-head-row2">
      <PurchasePlanMonthNav :y="y" :m="m" @prev="emit('prev')" @next="emit('next')" @reset="emit('reset')" />
      <PurchasePlanKpiStrip v-bind="kpi" />
    </div>
  </div>
</template>

<script setup lang="ts">
// 出货计划页头部两行（方案B，2026-11-28 owner 拍板合并两 Tab 后重写）——
// 只负责布局与转发：数据由父级传入，交互一律上抛事件，判定/聚合仍在原处。
import PurchasePlanFactoryFilter from './PurchasePlanFactoryFilter.vue'
import PurchasePlanToolbar from './PurchasePlanToolbar.vue'
import PurchasePlanMonthNav from './PurchasePlanMonthNav.vue'
import PurchasePlanKpiStrip from './PurchasePlanKpiStrip.vue'

// Boolean prop 缺省会被 Vue 转成 false，这里显式默认 true（旧调用方/单测保持原行为）
withDefaults(defineProps<{
  y: number
  m: number
  factories: string[]
  factoryTotals: Record<string, number>
  /** 写权限（透传给工具栏，控制「新建计划」是否展示） */
  canManage?: boolean
  kpi: {
    planQty: number
    planDays: number
    custN: number
    skuN: number
    peakDay: number
    peakQty: number
    riskDays: number
    riskOverdue: number
    riskExpiring: number
    riskQty: number
  }
}>(), { canManage: true })

const factory = defineModel<string>('factory', { required: true })
const globalKw = defineModel<string>('globalKw', { required: true })

const emit = defineEmits<{ prev: []; next: []; reset: []; export: []; create: [] }>()
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

/* 头部两行：第一行「看哪个工厂 + 做什么」，第二行「看哪个月 + 这个月怎么样」。 */
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
