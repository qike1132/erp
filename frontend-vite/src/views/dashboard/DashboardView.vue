<template>
  <div class="dashboard">
    <!-- 加载遮罩 -->
    <div
      v-if="isLoading"
      class="fixed inset-0 z-50 flex items-center justify-center bg-surface/60 backdrop-blur-sm"
    >
      <div class="flex flex-col items-center gap-3">
        <div class="w-10 h-10 rounded-[var(--radius-md)] bg-ocean-light flex items-center justify-center animate-pulse">
          <i class="fas fa-spinner fa-spin text-ocean-text text-lg" />
        </div>
        <span class="text-sm text-text-secondary font-medium">数据加载中...</span>
      </div>
    </div>

    <!-- 错误提示条 -->
    <div
      v-if="errorMessage"
      class="mb-4 p-3 rounded-[var(--radius-card)] bg-danger-50 border border-danger-200 flex items-center gap-3 animate-fade-in"
    >
      <div class="w-7 h-7 rounded-[var(--radius-md)] bg-danger-100 flex items-center justify-center shrink-0">
        <i class="fas fa-triangle-exclamation text-danger-500 text-xs" />
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-sm text-danger-700 font-medium">{{ errorMessage }}</p>
        <p class="text-xs text-danger-500 mt-0.5">{{ errorDetail }}</p>
      </div>
      <button
        class="px-3 py-1.5 rounded-[var(--radius-button)] bg-danger-500 text-white text-xs font-semibold hover:bg-danger-600 transition-all duration-300 hover:-translate-y-0.5 shrink-0"
        @click="retryLoad"
      >
        <i class="fas fa-rotate-right mr-1" />重试
      </button>
    </div>

    <!-- 大卡片容器 -->
    <div class="pc-card pc-card-main">
      <!-- 卡片头部 -->
      <div class="pc-card-header">
        <div class="pc-header-left">
          <div class="pc-card-title-group">
            <div class="pc-icon-box pc-icon-blue">
              <i class="fas fa-chart-line" />
            </div>
            <div>
              <h3>数据概览</h3>
              <small>实时监控业务核心指标</small>
            </div>
          </div>
        </div>
        <div class="pc-header-right">
          <span v-if="lastSyncTime" class="text-[11px] text-text-muted">
            更新于 {{ lastSyncTime }}
          </span>
        </div>
      </div>

      <!-- 卡片主体 -->
      <div class="pc-body">
        <!-- Hero 欢迎区 -->
        <div class="home-hero p-[28px_24px] md:p-[40px_36px] mb-6">
          <div class="flex items-center gap-3 md:gap-5 relative z-[1]">
            <img src="/logo_plush.png" alt="滨发玩具" class="w-12 h-12 md:w-16 md:h-16 rounded-[var(--radius-lg)] shadow-md" />
            <div>
              <h1 class="text-xl md:text-[28px] font-semibold text-text mb-1 tracking-tight">
                滨发玩具协同系统
              </h1>
              <p class="text-xs md:text-[14px] text-text-secondary leading-relaxed max-w-[600px] m-0">
                专业的毛绒玩具企业供应链管理平台 — 智能、高效、可靠的数字化管理解决方案
              </p>
            </div>
          </div>
        </div>

        <!-- KPI 指标卡片区 -->
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

        <!-- 图表区 -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <!-- 订单趋势图 -->
          <UiCard class="lg:col-span-2" header-gradient>
            <template #header>
              <div class="flex items-center justify-between w-full">
                <div class="flex items-center gap-2">
                  <div class="w-8 h-8 rounded-[var(--radius-md)] bg-primary-50 flex items-center justify-center">
                    <i class="fas fa-chart-line text-primary-500 text-sm" />
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
                  <i class="fas fa-chart-pie text-purple-500 text-sm" />
                </div>
                <span class="text-sm font-semibold text-text">订单与备货分布</span>
              </div>
            </template>
            <div ref="stockChartRef" class="h-[260px] md:h-[300px]" />
          </UiCard>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import KpiCard from './components/KpiCard.vue'
import { dashboardApi } from '@/api'
import { usePerfMark } from '@/composables/usePerfMark'
import { toast } from '@/composables/useToast'
import * as echartsModule from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

let _echartsReady = false
function ensureEcharts() {
  if (!_echartsReady) {
    echartsModule.use([
      LineChart,
      PieChart,
      GridComponent,
      TooltipComponent,
      LegendComponent,
      CanvasRenderer,
    ])
    _echartsReady = true
  }
  return echartsModule
}
const echarts = new Proxy(echartsModule, {
  get(_target, prop) {
    ensureEcharts()
    return Reflect.get(echartsModule, prop)
  },
}) as typeof echartsModule

const perf = usePerfMark('dashboard')

// ===== 数据状态 =====
const stats = ref<Record<string, number> | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const errorDetail = ref('')
const lastSyncTime = ref('')
const orderChartRef = ref<HTMLElement>()
const stockChartRef = ref<HTMLElement>()

const chartInstances: echarts.ECharts[] = []
const resizeHandlers: (() => void)[] = []
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ===== KPI 卡片数据 =====
const kpiCards = computed(() => [
  {
    key: 'orders',
    label: '今日订单',
    value: stats.value?.order_today ?? 0,
    trend: trendValue(stats.value?.order_today, stats.value?.order_yesterday),
    trendText: trendText(stats.value?.order_today, stats.value?.order_yesterday),
    icon: 'fa-cart-shopping',
    accent: 'blue' as const,
  },
  {
    key: 'stockin',
    label: '今日备货',
    value: stats.value?.stockin_today ?? 0,
    trend: trendValue(stats.value?.stockin_today, stats.value?.stockin_yesterday),
    trendText: trendText(stats.value?.stockin_today, stats.value?.stockin_yesterday),
    icon: 'fa-warehouse',
    accent: 'green' as const,
  },
  {
    key: 'stockout',
    label: '今日出货',
    value: stats.value?.stockout_today ?? 0,
    trend: trendValue(stats.value?.stockout_today, stats.value?.stockout_yesterday),
    trendText: trendText(stats.value?.stockout_today, stats.value?.stockout_yesterday),
    icon: 'fa-truck-fast',
    accent: 'amber' as const,
  },
  {
    key: 'pending',
    label: '待审批',
    value: stats.value?.pending_approvals ?? 0,
    trend: 0,
    trendText: '',
    icon: 'fa-clipboard-check',
    accent: 'red' as const,
  },
  {
    key: 'material',
    label: '待备料',
    value: stats.value?.pending_materials ?? 0,
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

// ===== 图表渲染 =====
function renderOrderChart() {
  if (!orderChartRef.value) return
  perf.mark('chart-order-start')
  const chart = echarts.init(orderChartRef.value)
  const days: string[] = []
  const now = new Date()
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    days.push(`${d.getMonth() + 1}/${d.getDate()}`)
  }

  const data = [0, 0, 0, 0, 0, 0, stats.value?.order_today ?? 0]

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#1a1a2e', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 12px;',
    },
    grid: { top: 24, right: 20, bottom: 32, left: 48 },
    xAxis: {
      type: 'category',
      data: days,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
      axisLabel: { color: '#64748b', fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      showSymbol: false,
      data,
      lineStyle: { color: '#5b8def', width: 3, cap: 'round' },
      itemStyle: { color: '#5b8def', borderWidth: 2, borderColor: '#fff' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(91,141,239,0.2)' },
          { offset: 1, color: 'rgba(91,141,239,0.01)' },
        ]),
      },
      emphasis: {
        showSymbol: true,
        itemStyle: { shadowBlur: 8, shadowColor: 'rgba(91,141,239,0.4)' },
      },
    }],
  })
  perf.markEnd('chart-order-start')
  perf.measure('chart-order-render', 'chart-order-start')
  chartInstances.push(chart)
  const onResize = () => chart.resize()
  resizeHandlers.push(onResize)
  window.addEventListener('resize', onResize)
}

function renderStockChart() {
  if (!stockChartRef.value) return
  perf.mark('chart-stock-start')
  const chart = echarts.init(stockChartRef.value)
  const orderTotal = stats.value?.order_today ?? 0
  const stockinTotal = stats.value?.stockin_today ?? 0

  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c}件 ({d}%)',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      textStyle: { color: '#1a1a2e', fontSize: 12 },
      extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,0.08); border-radius: 12px;',
    },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 20,
      textStyle: { color: '#64748b', fontSize: 12 },
    },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: false,
      padAngle: 3,
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 3 },
      label: { show: false },
      emphasis: {
        label: {
          show: true,
          fontSize: 14,
          fontWeight: 'bold',
          formatter: '{b}\n{d}%',
        },
        scaleSize: 6,
      },
      data: [
        { value: orderTotal, name: '订单数量', itemStyle: { color: '#5b8def' } },
        { value: stockinTotal, name: '备货数量', itemStyle: { color: '#28c76f' } },
      ],
    }],
  })
  perf.markEnd('chart-stock-start')
  perf.measure('chart-stock-render', 'chart-stock-start')
  chartInstances.push(chart)
  const onResize = () => chart.resize()
  resizeHandlers.push(onResize)
  window.addEventListener('resize', onResize)
}

// ===== 数据加载（含错误处理和日志） =====
async function loadStats(showLoading = true) {
  if (showLoading) isLoading.value = true
  errorMessage.value = ''
  errorDetail.value = ''
  perf.mark('api-start')

  try {
    // request.ts 的 axios 拦截器已 unwrap 一层 response.data，
    // 因此 dashboardApi.stats() 返回的就是后端的 { success, data } 包装对象。
    // 但在 401/网络异常时它可能是一个 AxiosError，会被 try/catch 捕获。
    const resp = await dashboardApi.stats() as { success?: boolean; data?: Record<string, number> } | Record<string, number>

    // 兼容多种返回结构：包装体 / 扁平对象 / undefined
    let raw: Record<string, number> | undefined
    if (resp && typeof resp === 'object') {
      if ('data' in resp && resp.data && typeof resp.data === 'object') {
        raw = resp.data as Record<string, number>
      } else if ('order_today' in resp || 'stockin_today' in resp || 'pending_approvals' in resp) {
        raw = resp as Record<string, number>
      }
    }

    if (!raw) {
      throw new Error('API 返回数据格式异常：data 字段缺失或非对象类型')
    }

    // 数据校验与类型转换（容错处理：所有字段安全转为 number）
    const validated: Record<string, number> = {
      order_today: Number(raw.order_today) || 0,
      order_yesterday: Number(raw.order_yesterday) || 0,
      stockin_today: Number(raw.stockin_today) || 0,
      stockin_yesterday: Number(raw.stockin_yesterday) || 0,
      stockout_today: Number(raw.stockout_today) || 0,
      stockout_yesterday: Number(raw.stockout_yesterday) || 0,
      pending_approvals: Number(raw.pending_approvals) || 0,
      low_stock_count: Number(raw.low_stock_count) || 0,
      pending_purchases: Number(raw.pending_purchases) || 0,
      pending_materials: Number(raw.pending_materials) || 0,
    }

    stats.value = validated
    lastSyncTime.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[Dashboard] 数据加载成功:', validated)
    }
  } catch (err: unknown) {
    const axiosError = err as { response?: { status?: number; data?: unknown }; message?: string; code?: string }

    let msg = '数据加载失败'
    let detail = ''

    if (axiosError.response) {
      const status = axiosError.response.status
      if (status === 401) {
        msg = '登录已过期，正在跳转...'
        detail = '请重新登录后查看数据'
      } else if (status === 403) {
        msg = '权限不足，无法访问仪表盘数据'
      } else if (status >= 500) {
        msg = '服务器内部错误，请稍后重试'
        detail = `HTTP ${status}`
      } else {
        msg = `请求失败 (HTTP ${status})`
      }
      if (axiosError.response.data && typeof axiosError.response.data === 'object') {
        const data = axiosError.response.data as Record<string, unknown>
        if (data.detail) detail = String(data.detail)
        else if (data.message) detail = String(data.message)
      }
    } else if (axiosError.code === 'ECONNABORTED') {
      msg = '请求超时，请检查网络连接'
    } else if (axiosError.code === 'ERR_NETWORK') {
      msg = '网络连接失败，请检查网络状态'
    } else if (axiosError.message) {
      // 兜底：直接显示错误信息（如格式校验抛出的 Error）
      msg = axiosError.message
    }

    errorMessage.value = msg
    errorDetail.value = detail
    if (!axiosError.response || axiosError.response.status !== 401) {
      toast.error(msg, { duration: 4000, closable: true })
    }

    // 降级：使用默认值确保页面可正常显示
    stats.value = {
      order_today: 0, order_yesterday: 0,
      stockin_today: 0, stockin_yesterday: 0,
      stockout_today: 0, stockout_yesterday: 0,
      pending_approvals: 0, low_stock_count: 0,
      pending_purchases: 0, pending_materials: 0,
    }

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[Dashboard] 数据加载失败:', err)
    }
  } finally {
    if (showLoading) isLoading.value = false
    perf.markEnd('api-start')
    perf.measure('api-stats', 'api-start')
  }

  await nextTick()
  renderOrderChart()
  renderStockChart()
  perf.markMountEnd()
  perf.measureFromMount('full-interactive')
}

// ===== 重试加载 =====
function retryLoad() {
  // 清理旧图表实例
  for (const chart of chartInstances) {
    chart.dispose()
  }
  chartInstances.length = 0
  loadStats(true)
}

// ===== 自动刷新机制（每5分钟） =====
function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[Dashboard] 自动刷新数据...')
    }
    loadStats(false)
  }, 5 * 60 * 1000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// ===== 生命周期 =====
onMounted(() => {
  loadStats(true)
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
  for (const handler of resizeHandlers) {
    window.removeEventListener('resize', handler)
  }
  resizeHandlers.length = 0
  for (const chart of chartInstances) {
    chart.dispose()
  }
  chartInstances.length = 0
})
</script>

<style scoped>
.home-hero {
  background: linear-gradient(135deg, var(--color-surface-card) 0%, var(--color-ocean-light) 100%);
  border-radius: var(--radius-card);
  border: 2px solid var(--color-ocean-light);
  box-shadow:
    0 4px 20px rgba(176, 224, 230, 0.25),
    0 4px 16px rgba(0, 0, 0, 0.06);
  position: relative;
  overflow: hidden;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.home-hero:hover {
  transform: translateY(-1px) scale(1.01);
  box-shadow: 0 8px 25px rgba(135, 206, 235, 0.35);
}

.home-hero::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -10%;
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, var(--color-ocean) 0%, transparent 70%);
  opacity: 0.15;
  border-radius: 50%;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* === Layout (same as PurchaseView) === */
.pc-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.pc-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}
.pc-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.pc-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
  gap: 12px;
}

.pc-header-left {
  flex: 1;
  display: flex;
  align-items: center;
}

.pc-header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.pc-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.pc-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.pc-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

.pc-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.pc-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

.pc-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px;
}
</style>
