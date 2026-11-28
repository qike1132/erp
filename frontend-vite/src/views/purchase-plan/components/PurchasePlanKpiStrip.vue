<template>
  <div class="sp-kpi-strip">
    <div class="sp-kpi">
      <span class="sp-kpi-l">本月计划</span>
      <span class="sp-kpi-v num">{{ fmt(planQty) }}</span>
      <span class="sp-kpi-s num">件 · {{ planDays }} 个排产日</span>
    </div>

    <div class="sp-kpi">
      <span class="sp-kpi-l">客户</span>
      <span class="sp-kpi-v num">{{ custN }}</span>
      <span class="sp-kpi-s">家</span>
    </div>

    <div class="sp-kpi">
      <span class="sp-kpi-l">SKU</span>
      <span class="sp-kpi-v num">{{ skuN }}</span>
      <span class="sp-kpi-s">个</span>
    </div>

    <div class="sp-kpi">
      <span class="sp-kpi-l">峰值日</span>
      <span class="sp-kpi-v num">{{ peakLabel }}</span>
      <span v-if="peakQty > 0" class="sp-kpi-s num">{{ fmt(peakQty) }} 件</span>
    </div>

    <!-- 风险只在这一格出现：明细在月历下方的风险条与格子标记上，条上给天数 -->
    <div class="sp-kpi sp-kpi-risk">
      <span class="sp-kpi-l">风险</span>
      <span class="sp-kpi-v num">{{ riskDays }} 天</span>
      <span class="sp-kpi-s num">{{ riskBreakdown }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// 一行信息条（方案B，2026-11-28 owner 拍板）：本月计划 / 客户 / SKU / 峰值日 / 风险 五格，
// 约 40px 单行——替代原四格大数字 KPI（已生产/待生产/完成率仍在下方 SKU 月度统计表按行给）。
// 只做展示：数值由父级传入，判定与聚合仍在原处，避免两处各算一遍。
import { computed } from 'vue'
import { formatNumber as fmt } from '@/utils/format' // L-15（2026-11-21 审计）：删除 8 处各自为政的本地 fmt，统一千分位口径

const props = defineProps<{
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
}>()

const peakLabel = computed(() => (props.peakQty > 0 ? `${props.peakDay}日` : '—'))

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
  border-radius: var(--radius-sm, 10px);
  overflow: hidden;
}

/* 单行信息条：标签 + 大数字 + 补充说明排在一条基线上，整条约 40px 高 */
.sp-kpi {
  flex: 1 1 120px;
  min-width: 0;
  padding: 9px 14px;
  background: white;
  display: flex;
  align-items: baseline;
  gap: 7px;
  white-space: nowrap;
  overflow: hidden;
}

.sp-kpi-l {
  flex-shrink: 0;
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-muted, #5a6b8c);
}

.sp-kpi-v {
  font-size: var(--fs-heading-3);
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.sp-kpi-s {
  font-size: var(--fs-caption);
  color: var(--color-text-muted, #8c96ad);
  overflow: hidden;
  text-overflow: ellipsis;
}

.sp-kpi-risk .sp-kpi-l,
.sp-kpi-risk .sp-kpi-v {
  color: var(--color-danger-600);
}
</style>
