<template>
  <!-- 图表区（自 DashboardView.vue 原样搬移） -->
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <!-- 订单趋势图 -->
    <UiCard class="lg:col-span-2" header-gradient>
      <template #header>
        <div class="flex items-center justify-between w-full">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-[var(--radius-md)] bg-primary-50 flex items-center justify-center">
              <FontAwesomeIcon icon="chart-line" class="text-primary-500 text-sm" />
            </div>
            <span class="text-sm font-semibold text-text">订单趋势（近7日）</span>
          </div>
          <span class="text-xs text-text-muted">单位：件</span>
        </div>
      </template>
      <div ref="orderChartRef" class="h-[260px] md:h-[300px]" />
    </UiCard>

    <!-- 订单与备货分布图 -->
    <UiCard header-gradient>
      <template #header>
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-[var(--radius-md)] bg-purple-50 flex items-center justify-center">
            <FontAwesomeIcon icon="chart-pie" class="text-purple-500 text-sm" />
          </div>
          <span class="text-sm font-semibold text-text">订单与备货分布</span>
        </div>
      </template>
      <div ref="stockChartRef" class="h-[260px] md:h-[300px]" />
    </UiCard>
  </div>
</template>

<script setup lang="ts">
/**
 * DashboardChartsSection — 仪表盘图表区（订单趋势 + 订单与备货分布）
 * 模板与图表渲染/更新/销毁逻辑自 DashboardView.vue 原样搬移。
 * 渲染时机由父组件在数据加载后调用 renderOrUpdate() 接管，
 * 保持原有「首次完整渲染、后续仅更新数据（不复建实例）」的行为。
 */
import { ref, onUnmounted } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import { usePerfMark } from '@/composables/usePerfMark'
import type { StockStats } from '../composables/useDashboardStats'

// ECharts 懒加载：避免在首屏（dashboard 为落地页）加载 ~1MB 的图表库
// 🟢 改为共享预加载模块：登录成功后即开始下载，dashboard 挂载时直接复用缓存
import { ensureEcharts, getEchartsModule } from '@/utils/echartsPreload'
type EChartsModule = typeof import('echarts/core')

type PerfMark = ReturnType<typeof usePerfMark>

const props = defineProps<{
  /** 仪表盘统计数据（驱动订单趋势图） */
  stats: Record<string, number> | null
  /** 库存统计数据（驱动订单与备货分布图） */
  stockStats: StockStats | null
  /** 性能打点（与父组件共享同一实例） */
  perf: PerfMark
}>()

/**
 * 安全初始化图表：若 DOM 已有旧实例则先 dispose。
 * 消除 "There is a chart instance already initialized on the dom" 警告，
 * 杜绝自动刷新时的实例堆积与内存泄露。
 */
function safeInit(dom: HTMLElement, echarts: EChartsModule): ReturnType<EChartsModule['init']> {
  const existing = echarts.getInstanceByDom(dom)
  if (existing) existing.dispose()
  return echarts.init(dom)
}

// ===== 图表 DOM 引用 =====
const orderChartRef = ref<HTMLElement>()
const stockChartRef = ref<HTMLElement>()

// 图表 & resize 生命周期统一管理
const _chartMeta: { chart: import('echarts/core').ECharts; handler: () => void }[] = []
/** 图表具名引用：消除 _chartMeta[0]/[1] 硬编码，支持任意图表增删 */
let _orderChart: import('echarts/core').ECharts | null = null
let _stockChart: import('echarts/core').ECharts | null = null

/** 销毁所有图表实例并移除 resize 监听，确保零泄露 */
function disposeAllCharts() {
  for (const { chart, handler } of _chartMeta) {
    window.removeEventListener('resize', handler)
    chart.dispose()
  }
  _chartMeta.length = 0
  _orderChart = null
  _stockChart = null
}

/** 注册图表到生命周期管理器（resize + dispose 由 disposeAllCharts 统一处理） */
function registerChart(chart: import('echarts/core').ECharts) {
  const handler = () => chart.resize()
  window.addEventListener('resize', handler)
  _chartMeta.push({ chart, handler })
}

/** 构建折线图 option（数据和日期可变，样式固定） */
function buildOrderChartOption(echarts: EChartsModule) {
  const days: string[] = []
  const now = new Date()
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    days.push(`${d.getMonth() + 1}/${d.getDate()}`)
  }
  const data = [0, 0, 0, 0, 0, 0, props.stats?.order_today ?? 0]
  return {
    tooltip: {
      trigger: 'axis' as const,
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#1a1a2e', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 12px;',
    },
    grid: { top: 24, right: 20, bottom: 32, left: 48 },
    xAxis: {
      type: 'category' as const, data: days,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' as const } },
      axisLabel: { color: '#64748b', fontSize: 11 },
      axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'line' as const, smooth: true, symbol: 'circle' as const, symbolSize: 8,
      showSymbol: false, data,
      lineStyle: { color: '#5b8def', width: 3, cap: 'round' as const },
      itemStyle: { color: '#5b8def', borderWidth: 2, borderColor: '#fff' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(91,141,239,0.2)' },
          { offset: 1, color: 'rgba(91,141,239,0.01)' },
        ]),
      },
      emphasis: { showSymbol: true, itemStyle: { shadowBlur: 8, shadowColor: 'rgba(91,141,239,0.4)' } },
    }],
  }
}

/** 构建饼图 option（数据可变，样式固定） */
function buildStockChartOption() {
  const orderTotal = props.stockStats?.order_quantity ?? 0
  const stockinTotal = props.stockStats?.stockin_quantity ?? 0
  return {
    tooltip: {
      trigger: 'item' as const, formatter: '{b}: {c}件 ({d}%)',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e2e8f0', borderWidth: 1,
      textStyle: { color: '#1a1a2e', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 12px;',
    },
    legend: {
      bottom: 0, itemWidth: 10, itemHeight: 10, itemGap: 20,
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    series: [{
      type: 'pie' as const, radius: ['42%', '68%'], center: ['50%', '46%'],
      avoidLabelOverlap: true, padAngle: 0, minAngle: 15,
      itemStyle: { borderColor: '#fff', borderWidth: 0 },
      label: {
        show: true, fontSize: 12, fontWeight: 'bold' as const,
        formatter: '{b}\n{c}件 ({d}%)', overflow: 'break' as const, width: 100,
      },
      labelLayout: { hideOverlap: true },
      emphasis: {
        label: { show: true, fontSize: 13, fontWeight: 'bold' as const, formatter: '{b}\n{c}件 ({d}%)' },
        scaleSize: 6,
      },
      data: [
        { value: orderTotal, name: '订单数量', itemStyle: { color: '#28c76f' } },
        { value: stockinTotal, name: '备货数量', itemStyle: { color: '#5b8def' } },
      ],
    }],
  }
}

/** 标记图表是否已完成首次完整渲染（之后仅更新数据，不复建实例） */
let _chartsRendered = false

async function renderOrderChart() {
  if (!orderChartRef.value) return
  props.perf.mark('chart-order-start')
  const echarts = await ensureEcharts()
  const chart = safeInit(orderChartRef.value, echarts)
  chart.setOption(buildOrderChartOption(echarts))
  props.perf.markEnd('chart-order-start')
  props.perf.measure('chart-order-render', 'chart-order-start')
  registerChart(chart)
  _orderChart = chart
}

async function renderStockChart() {
  if (!stockChartRef.value) return
  props.perf.mark('chart-stock-start')
  const echarts = await ensureEcharts()
  const chart = safeInit(stockChartRef.value, echarts)
  chart.setOption(buildStockChartOption())
  props.perf.markEnd('chart-stock-start')
  props.perf.measure('chart-stock-render', 'chart-stock-start')
  registerChart(chart)
  _stockChart = chart
}

/** 仅更新图表数据（不复建实例）：用于自动刷新，近乎零开销 */
function updateOrderChart() {
  if (!_orderChart) return
  _orderChart.setOption(buildOrderChartOption(getEchartsModule()!))
}

function updateStockChart() {
  if (!_stockChart) return
  _stockChart.setOption(buildStockChartOption())
}

/**
 * 数据加载后渲染/更新图表（由父组件在 nextTick 后调用）。
 * 首次完整渲染图表；后续自动刷新仅更新数据（不复建实例）。
 */
async function renderOrUpdate() {
  if (!_chartsRendered) {
    await renderOrderChart()
    await renderStockChart()
    _chartsRendered = true
  } else {
    updateOrderChart()
    updateStockChart()
  }
}

/** 重置图表状态（重试加载时调用：销毁全部实例并允许重建） */
function resetCharts() {
  _chartsRendered = false
  disposeAllCharts()
}

// 组件卸载时销毁所有图表实例（保留原有清理接线）
onUnmounted(() => {
  _chartsRendered = false
  disposeAllCharts()
})

defineExpose({
  renderOrUpdate,
  resetCharts,
})
</script>
