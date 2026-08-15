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
        <DashboardKpiSection :stats="stats" :is-loading="isLoading" />

        <!-- 图表区 -->
        <DashboardChartsSection ref="chartsRef" :stats="stats" :stock-stats="stockStats" :perf="perf" />
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
/**
 * DashboardView — 仪表盘主容器
 * 拆分后职责：工具栏/弹窗/生命周期编排。
 *  - KPI 指标卡片区 → DashboardKpiSection（复用既有 KpiCard/CountUp）
 *  - 图表区（渲染/更新/销毁）→ DashboardChartsSection
 *  - 数据加载 → useDashboardStats
 *  - 自动刷新 / 时钟 → useDashboardAutoRefresh / useDashboardClock
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import NotificationBell from '@/layouts/components/NotificationBell.vue'
import DashboardKpiSection from './components/DashboardKpiSection.vue'
import DashboardChartsSection from './components/DashboardChartsSection.vue'
import { useDashboardStats } from './composables/useDashboardStats'
import { useDashboardAutoRefresh } from './composables/useDashboardAutoRefresh'
import { useDashboardClock } from './composables/useDashboardClock'
import { authApi, orderApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useSidebarStore } from '@/stores/sidebar'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePerfMark } from '@/composables/usePerfMark'

const perf = usePerfMark('dashboard')

// ===== 工具栏状态（合并自原 DefaultLayout 顶部 header）=====
const authStore = useAuthStore()
const sidebarStore = useSidebarStore()
const logoutConfirm = useConfirmDialog()
const router = useRouter()
const avatarLetter = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

// ===== 时钟 =====
const { currentTime, startClock, stopClock } = useDashboardClock()

// ===== 数据状态（加载/错误/降级）=====
const {
  stats,
  stockStats,
  isLoading,
  errorMessage,
  errorDetail,
  loadStats: loadStatsData,
} = useDashboardStats()

// ===== 图表区引用（渲染时机由本组件在数据加载后驱动）=====
const chartsRef = ref<InstanceType<typeof DashboardChartsSection> | null>(null)

// ===== 数据加载 + 图表渲染（保持原有时序：数据 → nextTick → 首渲/仅更新数据） =====
async function loadStats(showLoading = true) {
  await loadStatsData(showLoading)
  await nextTick()
  // 🟢 首次完整渲染图表；后续自动刷新仅更新数据（不复建实例）
  try {
    await chartsRef.value?.renderOrUpdate()
  } catch (chartErr) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[Dashboard] 图表渲染失败:', chartErr)
    }
  }
  perf.markMountEnd()
  perf.measureFromMount('full-interactive')
}

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

// ===== 重试加载（销毁全部图表实例后重新加载并完整渲染） =====
function retryLoad() {
  chartsRef.value?.resetCharts()
  loadStats(true).catch((err) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[Dashboard] retryLoad failed:', err)
    }
  })
}

// ===== 自动刷新（每 30 秒，确保"今日备货/今日出货/待审批/待备料"等模块实时显示） =====
const { startAutoRefresh, stopAutoRefresh } = useDashboardAutoRefresh(() => {
  loadStats(false).catch((err) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[Dashboard] 自动刷新加载失败:', err)
    }
  })
})

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
  startClock()
})

onUnmounted(() => {
  stopAutoRefresh()
  stopClock()
  // 图表实例（_chartsRendered/disposeAllCharts）由 DashboardChartsSection
  // 的 onUnmounted 清理，接线保留
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
