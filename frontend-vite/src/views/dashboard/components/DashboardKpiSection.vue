<template>
  <!-- KPI 指标卡片区（自 DashboardView.vue 原样搬移） -->
  <div class="grid grid-cols-2 lg:grid-cols-5 gap-3 md:gap-4 mb-6">
    <KpiCard
      v-for="(card, index) in kpiCards"
      :key="card.key"
      :label="card.label"
      :value="card.value"
      :trend="card.trend"
      :trend-text="card.trendText"
      :icon="card.icon"
      :accent="card.accent"
      :delay="index * 80"
      :is-loading="isLoading"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * DashboardKpiSection — 仪表盘 KPI 指标卡片区
 * 模板与数据映射自 DashboardView.vue 原样搬移（复用既有 KpiCard/CountUp）。
 */
import { computed } from 'vue'
import KpiCard from './KpiCard.vue'

const props = defineProps<{
  /** 仪表盘统计数据（null 表示未加载） */
  stats: Record<string, number> | null
  /** 是否加载中 */
  isLoading: boolean
}>()

// ===== KPI 卡片数据 =====
const kpiCards = computed(() => [
  {
    key: 'orders',
    label: '今日订单',
    value: props.stats?.order_today ?? 0,
    trend: trendValue(props.stats?.order_today, props.stats?.order_yesterday),
    trendText: trendText(props.stats?.order_today, props.stats?.order_yesterday),
    icon: 'fa-cart-shopping',
    accent: 'blue' as const,
  },
  {
    key: 'stockin',
    label: '今日备货',
    value: props.stats?.stockin_today ?? 0,
    trend: trendValue(props.stats?.stockin_today, props.stats?.stockin_yesterday),
    trendText: trendText(props.stats?.stockin_today, props.stats?.stockin_yesterday),
    icon: 'fa-warehouse',
    accent: 'green' as const,
  },
  {
    key: 'stockout',
    label: '今日出货',
    value: props.stats?.stockout_today ?? 0,
    trend: trendValue(props.stats?.stockout_today, props.stats?.stockout_yesterday),
    trendText: trendText(props.stats?.stockout_today, props.stats?.stockout_yesterday),
    icon: 'fa-truck-fast',
    accent: 'amber' as const,
  },
  {
    key: 'pending',
    label: '待审批',
    value: props.stats?.pending_approvals ?? 0,
    trend: 0,
    trendText: '',
    icon: 'fa-clipboard-check',
    accent: 'red' as const,
  },
  {
    key: 'material',
    label: '待备料',
    value: props.stats?.pending_materials ?? 0,
    trend: 0,
    trendText: '',
    icon: 'fa-cubes',
    accent: 'ocean' as const,
  },
])

// ===== 趋势计算 =====
function trendValue(today?: number, yesterday?: number): number {
  if (today == null || yesterday == null || yesterday === 0) return 0
  return Math.round(((today - yesterday) / yesterday) * 100)
}

function trendText(today?: number, yesterday?: number): string {
  if (today == null || yesterday == null) return ''
  if (yesterday === 0) return today > 0 ? '↑ 新增' : '— 持平'
  const pct = Math.round(((today - yesterday) / yesterday) * 100)
  if (pct > 0) return `↑ ${pct}%`
  if (pct < 0) return `↓ ${Math.abs(pct)}%`
  return '— 持平'
}
</script>
