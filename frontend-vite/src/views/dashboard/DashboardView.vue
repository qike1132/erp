<template>
  <div class="dashboard">
    <!-- 加载遮罩 -->
    <div
      v-if="isLoading"
      class="fixed inset-0 z-50 flex items-center justify-center bg-surface/60 backdrop-blur-sm"
    >
      <div class="flex flex-col items-center gap-3">
        <div class="w-10 h-10 rounded-[var(--radius-md)] bg-ocean-light flex items-center justify-center animate-pulse">
          <UiSpinner />
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
        <FontAwesomeIcon icon="triangle-exclamation" class="text-danger-500 text-xs" />
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-sm text-danger-700 font-medium">{{ errorMessage }}</p>
        <p class="text-xs text-danger-500 mt-0.5">{{ errorDetail }}</p>
      </div>
      <button
        class="px-3 py-1.5 rounded-[var(--radius-button)] bg-danger-500 text-white text-xs font-semibold hover:bg-danger-600 transition-all duration-300 hover:-translate-y-0.5 shrink-0"
        @click="retryLoad"
      >
        <FontAwesomeIcon icon="rotate-right" class="mr-1" />重试
      </button>
    </div>

    <!-- 大卡片容器 -->
    <div class="page-card page-card-main">
      <!-- 工具栏（合并自原布局顶部 header：折叠/返回首页/时间/用户信息/退出） -->
      <div class="page-card-toolbar">
        <div class="page-toolbar-left">
          <button class="menu-toggle-btn" aria-label="切换侧边栏" @click="sidebarStore.toggle()">
            <FontAwesomeIcon :icon="!sidebarStore.isCollapsed ? 'angles-left' : 'angles-right'" style="font-size: 18px" aria-hidden="true" />
          </button>
        </div>
        <div class="page-toolbar-right">
          <!-- 统一工具栏：时间 / 通知 / 用户 / 退出 聚合为单一视觉单元 -->
          <div class="tb-cluster">
            <span class="tb-time">
              <FontAwesomeIcon icon="clock" aria-hidden="true" />
              {{ currentTime }}
            </span>
            <span class="tb-divider" aria-hidden="true" />
            <NotificationBell v-if="authStore.isLoggedIn" />
            <span class="tb-divider" aria-hidden="true" />
            <div class="tb-user">
              <div class="tb-avatar" aria-hidden="true">{{ avatarLetter }}</div>
              <div class="tb-user-text min-w-0">
                <div class="tb-name">{{ authStore.user?.username || '用户' }}</div>
                <div class="tb-role">{{ authStore.user?.is_super ? '超级管理员' : '普通用户' }}</div>
              </div>
            </div>
            <button class="tb-logout" @click="confirmLogout" aria-label="退出登录">
              <FontAwesomeIcon icon="right-from-bracket" aria-hidden="true" />
              <span>退出</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 卡片主体 -->
      <div class="page-card-body">
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
      </div>
    </div>

    <UiConfirmDialog
      :open="logoutConfirm.open"
      :text="logoutConfirm.text"
      :sub="logoutConfirm.sub"
      :type="logoutConfirm.type"
      @confirm="logoutConfirm.onConfirm"
      @cancel="logoutConfirm.onCancel"
    />

    <!-- 贝乐未确认订单提醒弹窗（登录后首次进 dashboard、存在未确认湖北订单时弹出一次） -->
    <UiConfirmDialog
      :open="beilePopupOpen"
      :text="beilePopupText"
      :sub="beilePopupSub"
      type="warning"
      :close-on-overlay-click="false"
      @confirm="goConfirmBeileOrders"
      @cancel="closeBeilePopup"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import UiCard from '@/components/ui/UiCard.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import NotificationBell from '@/layouts/components/NotificationBell.vue'
import KpiCard from './components/KpiCard.vue'
import { authApi, dashboardApi, stockApi, orderApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useSidebarStore } from '@/stores/sidebar'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePerfMark } from '@/composables/usePerfMark'
import { toast } from '@/composables/useToast'

// ECharts 懒加载：避免在首屏（dashboard 为落地页）加载 ~1MB 的图表库
// 🟢 改为共享预加载模块：登录成功后即开始下载，dashboard 挂载时直接复用缓存
import { ensureEcharts, getEchartsModule } from '@/utils/echartsPreload'
type EChartsModule = typeof import('echarts/core')

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

const perf = usePerfMark('dashboard')

// ===== 工具栏状态（合并自原 DefaultLayout 顶部 header）=====
const authStore = useAuthStore()
const sidebarStore = useSidebarStore()
const logoutConfirm = useConfirmDialog()
const router = useRouter()
const currentTime = ref('')
const avatarLetter = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

// ===== 数据状态 =====
// shallowRef：API 响应整体替换（不逐属性变更），避免深层响应式开销
const stats = shallowRef<Record<string, number> | null>(null)
const stockStats = shallowRef<{ order_quantity: number; order_regular_quantity: number; order_custom_quantity: number; stockin_quantity: number } | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
const errorDetail = ref('')
const lastSyncTime = ref('')
const orderChartRef = ref<HTMLElement>()
const stockChartRef = ref<HTMLElement>()

// ===== 贝乐未确认订单提醒弹窗 =====
const beilePopupOpen = ref(false)
const beilePopupText = ref('')
const beilePopupSub = ref('')
// sessionStorage 标记：每登录会话仅弹一次（登录成功时在 useLogin 中清除）
const BEILE_POPUP_KEY = 'beile_confirm_popup_shown'

/** 登录后首次进 dashboard：贝乐用户（factory=湖北）+ 存在未确认湖北订单时弹出提醒 */
async function checkBeileConfirmPopup() {
  try {
    // 仅贝乐用户（湖北工厂）弹出，其余用户（含超管）均不弹
    // 与后端 dispatch_beile_unconfirmed_notifications 派发对象（User.factory == '湖北'）一致
    if (authStore.user?.factory !== '湖北') return
    if (sessionStorage.getItem(BEILE_POPUP_KEY)) return

    const resp = await orderApi.beileList({ page: 1, per_page: 1 })
    const unconfirmed = Number((resp as { unconfirmed_count?: number })?.unconfirmed_count ?? 0)
    if (unconfirmed <= 0) return

    beilePopupText.value = `湖北新订单待确认：${unconfirmed} 个`
    beilePopupSub.value = '有订单尚未确认，请及时处理'
    beilePopupOpen.value = true
  } catch (err) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[Dashboard] 未确认订单提醒检查失败:', err)
    }
  }
}

function closeBeilePopup() {
  beilePopupOpen.value = false
  sessionStorage.setItem(BEILE_POPUP_KEY, '1')
}

function goConfirmBeileOrders() {
  closeBeilePopup()
  router.push('/beile-order')
}

// 图表 & resize 生命周期统一管理
const _chartMeta: { chart: import('echarts/core').ECharts; handler: () => void }[] = []
/** 图表具名引用：消除 _chartMeta[0]/[1] 硬编码，支持任意图表增删 */
let _orderChart: import('echarts/core').ECharts | null = null
let _stockChart: import('echarts/core').ECharts | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

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
/** 标记图表是否已完成首次完整渲染（之后仅更新数据，不复建实例） */
let _chartsRendered = false

/** 构建折线图 option（数据和日期可变，样式固定） */
function buildOrderChartOption(echarts: EChartsModule) {
  const days: string[] = []
  const now = new Date()
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now)
    d.setDate(d.getDate() - i)
    days.push(`${d.getMonth() + 1}/${d.getDate()}`)
  }
  const data = [0, 0, 0, 0, 0, 0, stats.value?.order_today ?? 0]
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
  const orderTotal = stockStats.value?.order_quantity ?? 0
  const stockinTotal = stockStats.value?.stockin_quantity ?? 0
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

async function renderOrderChart() {
  if (!orderChartRef.value) return
  perf.mark('chart-order-start')
  const echarts = await ensureEcharts()
  const chart = safeInit(orderChartRef.value, echarts)
  chart.setOption(buildOrderChartOption(echarts))
  perf.markEnd('chart-order-start')
  perf.measure('chart-order-render', 'chart-order-start')
  registerChart(chart)
  _orderChart = chart
}

async function renderStockChart() {
  if (!stockChartRef.value) return
  perf.mark('chart-stock-start')
  const echarts = await ensureEcharts()
  const chart = safeInit(stockChartRef.value, echarts)
  chart.setOption(buildStockChartOption())
  perf.markEnd('chart-stock-start')
  perf.measure('chart-stock-render', 'chart-stock-start')
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

// ===== 数据加载（含错误处理和日志） =====
async function loadStats(showLoading = true) {
  if (showLoading) isLoading.value = true
  errorMessage.value = ''
  errorDetail.value = ''
  perf.mark('api-start')

  // 先加载仪表盘统计，再加载库存统计（库存失败时可用仪表盘数据降级）
  await loadDashboardStats()
  await loadStockStats()

  if (showLoading) isLoading.value = false
  perf.markEnd('api-start')
  perf.measure('api-stats', 'api-start')

  await nextTick()
  // 🟢 首次完整渲染图表；后续自动刷新仅更新数据（不复建实例）
  try {
    if (!_chartsRendered) {
      await renderOrderChart()
      await renderStockChart()
      _chartsRendered = true
    } else {
      updateOrderChart()
      updateStockChart()
    }
  } catch (chartErr) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[Dashboard] 图表渲染失败:', chartErr)
    }
  }
  perf.markMountEnd()
  perf.measureFromMount('full-interactive')
}

async function loadDashboardStats() {
  try {
    const resp = await dashboardApi.stats() as { success?: boolean; data?: Record<string, number> } | Record<string, number>

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
      const status = axiosError.response.status ?? 0
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
      msg = axiosError.message
    }

    errorMessage.value = msg
    errorDetail.value = detail
    if (!axiosError.response || axiosError.response.status !== 401) {
      toast.error(msg, { duration: 4000, closable: true })
    }

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
  }
}

async function loadStockStats() {
  try {
    const resp = await stockApi.stats()
    if (resp) {
      stockStats.value = resp
    }
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[Dashboard] 库存统计数据加载成功:', stockStats.value)
    }
  } catch (err) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[Dashboard] 库存统计数据加载失败，使用降级数据:', err)
    }
    stockStats.value = { order_quantity: stats.value?.order_today ?? 0, order_regular_quantity: 0, order_custom_quantity: 0, stockin_quantity: stats.value?.stockin_today ?? 0 }
  }
}

// ===== 重试加载 =====
function retryLoad() {
  _chartsRendered = false
  disposeAllCharts()
  loadStats(true).catch((err) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[Dashboard] retryLoad failed:', err)
    }
  })
}

// ===== 自动刷新机制（每 30 秒，确保"今日备货/今日出货/待审批/待备料"等模块实时显示） =====
function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.log('[Dashboard] 自动刷新数据...')
    }
    loadStats(false)
  }, 30 * 1000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

// ===== 工具栏：时钟 =====
let clockTimer: ReturnType<typeof setInterval> | null = null

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ===== 工具栏：退出登录 =====
async function handleLogout() {
  try {
    await authApi.logout()
  } finally {
    authStore.logout()
    router.push('/login')
  }
}

async function confirmLogout() {
  const ok = await logoutConfirm.confirm('确定要退出登录吗？', '退出后需重新登录', 'danger')
  if (ok) handleLogout()
}

// ===== 生命周期 =====
onMounted(() => {
  // catch 防止 loadStats 内部未捕获的 reject 变成 unhandled rejection
  loadStats(true).catch((err) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[Dashboard] onMounted loadStats failed:', err)
    }
  })
  // 贝乐未确认订单提醒（登录后首次进 dashboard 弹一次）
  checkBeileConfirmPopup()
  startAutoRefresh()
  updateTime()
  clockTimer = setInterval(updateTime, 60_000)
})

onUnmounted(() => {
  stopAutoRefresh()
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  _chartsRendered = false
  disposeAllCharts()
})
</script>

<style scoped>
.dashboard {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.animate-fade-in {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* === 工具栏（已迁移到全局 .page-card-toolbar，src/styles/app.css） === */

.menu-toggle-btn {
  background: var(--color-surface-card);
  border: 2px solid var(--color-ocean);
  color: var(--color-text);
  width: 44px;
  height: 44px;
  border-radius: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: transform 0.2s ease, background 0.2s ease;
  box-shadow: 0 2px 8px rgba(176, 224, 230, 0.25);
  will-change: transform;
}

.menu-toggle-btn:hover {
  background: var(--color-ocean-light);
  transform: scale(1.05);
}

/* 统一工具栏胶囊：时间 / 通知 / 用户 / 退出 聚合为单一视觉单元 */
.tb-cluster {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px 4px 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(240, 244, 248, 0.95) 100%);
  border: 2px solid var(--color-ocean-light);
  box-shadow:
    0 2px 12px color-mix(in srgb, var(--color-ocean) 22%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition:
    transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.3s ease,
    box-shadow 0.3s ease;
}
.tb-cluster:hover {
  transform: translateY(-1px);
  border-color: var(--color-ocean-deep);
  box-shadow:
    0 6px 20px color-mix(in srgb, var(--color-ocean) 35%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 1);
}

.tb-time {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-tertiary);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.tb-divider {
  width: 1px;
  height: 22px;
  margin: 0 4px;
  background: var(--color-border-light);
}

.tb-user {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 2px 4px;
}

.tb-avatar {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--color-ocean) 0%, var(--color-ocean-deep) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
  font-weight: 700;
  font-size: 14px;
  box-shadow: 0 3px 10px color-mix(in srgb, var(--color-ocean) 25%, transparent);
  flex-shrink: 0;
}

.tb-user-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tb-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.2;
}

.tb-role {
  font-size: 11px;
  color: var(--color-text-tertiary);
  opacity: 0.85;
  line-height: 1.2;
}

.tb-logout {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--color-danger-700);
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s ease, color 0.2s ease;
}
.tb-logout:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-800);
}

@media (max-width: 768px) {
  .tb-time {
    display: none;
  }
}
</style>
