<template>
  <div class="sp-kpi-strip">
    <div class="sp-kpi">
      <span class="sp-kpi-l">本月计划</span>
      <span class="sp-kpi-v num">{{ fmt(planQty) }}</span>
      <span class="sp-kpi-s num">件 · {{ planDays }} 个排产日</span>
    </div>

    <div class="sp-kpi">
      <span class="sp-kpi-l">本月已生产</span>
      <span class="sp-kpi-v num">{{ fmt(producedQty) }}</span>
      <span class="sp-kpi-s num">件 · 待生产 {{ fmt(remainQty) }}</span>
    </div>

    <div class="sp-kpi sp-kpi-rate">
      <span class="sp-kpi-l">完成率</span>
      <span class="sp-kpi-v num">{{ pct }}%</span>
      <div class="sp-meter"><i :class="meterCls" :style="{ width: pct + '%' }" /></div>
    </div>

    <!-- 风险只在这一格出现：原先 KPI 条的「已延期」「临期≤3天」两格与右栏风险清单
         报的是同一件事，合并成一天数与明细两处（条上给天数，清单里给条目）。 -->
    <div class="sp-kpi sp-kpi-risk">
      <span class="sp-kpi-l">风险</span>
      <span class="sp-kpi-v num">{{ riskDays }} 天</span>
      <span class="sp-kpi-s num">{{ riskBreakdown }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// KPI 四格 —— 从 PurchasePlanView 抽出。
// 只做展示：数值由父级传入，判定与聚合仍在原处，避免两处各算一遍。
import { computed } from 'vue'

const props = defineProps<{
  planQty: number
  producedQty: number
  remainQty: number
  pct: number
  planDays: number
  riskDays: number
  riskOverdue: number
  riskExpiring: number
  riskQty: number
}>()

/** 千分位：几十万位的计划量不分组的话，量级要靠数位数才看得出来 */
function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}

const meterCls = computed(() => {
  if (props.pct <= 0) return 'sp-meter-r'
  if (props.pct < 100) return 'sp-meter-a'
  return 'sp-meter-g'
})

const riskBreakdown = computed(() => {
  if (props.riskDays <= 0) return '本月无逾期与临期'
  return `逾期 ${props.riskOverdue} · 临期 ${props.riskExpiring} · ${fmt(props.riskQty)}件`
})
</script>

<style scoped lang="scss">
.sp-kpi-strip {
  display: flex;
  align-items: stretch;
  flex: 1;
  min-width: 0;
  /* 分隔线用 1px 间隙透出底色实现：换行后横向/纵向分隔线都自然成立，
     且不会在外边缘留下多余边框（逐项 border 无法判断某行是否为末行）。 */
  gap: 1px;
  background: var(--color-border-light, #e2e8f0);
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-md, 14px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.sp-kpi {
  flex: 1 1 130px;
  min-width: 0;
  padding: 10px 14px;
  background: white;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sp-kpi-l {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted, #5a6b8c);
  white-space: nowrap;
}

.sp-kpi-v {
  font-size: 21px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
  margin-top: 3px;
}

.sp-kpi-s {
  font-size: 11px;
  color: var(--color-text-muted, #8c96ad);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 3px;
}

.sp-kpi-risk .sp-kpi-l,
.sp-kpi-risk .sp-kpi-v {
  color: var(--color-danger-600);
}

.sp-meter {
  height: 6px;
  border-radius: 3px;
  background: #edf0f6;
  overflow: hidden;
  margin-top: 8px;
  max-width: 200px;
}

.sp-meter > i {
  display: block;
  height: 100%;
  border-radius: 3px;
}

.sp-meter-r { background: var(--color-danger-500, #ea5455); }
.sp-meter-a { background: var(--color-warning-500, #ff9f43); }
.sp-meter-g { background: var(--color-success-500, #28c76f); }
</style>
