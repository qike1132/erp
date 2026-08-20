<template>
  <div class="dashboard">
    <DashboardErrorBanner
      v-if="errorMessage"
      :message="errorMessage"
      :detail="errorDetail"
      @retry="retryLoad"
    />

    <div class="page-card page-card-main">
      <DashboardToolbarSection
        :current-time="currentTime"
        :is-logged-in="authStore.isLoggedIn"
        :avatar-letter="avatarLetter"
        :username="authStore.user?.username || '用户'"
        :is-super="!!authStore.user?.is_super"
        @logout="confirmLogout"
      />

      <div class="page-card-body">
        <DashboardKpiSection :stats="stats" :is-loading="isLoading" />
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
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import DashboardErrorBanner from './components/DashboardErrorBanner.vue'
import DashboardToolbarSection from './components/DashboardToolbarSection.vue'
import DashboardKpiSection from './components/DashboardKpiSection.vue'
import DashboardChartsSection from './components/DashboardChartsSection.vue'
import { useDashboardStats } from './composables/useDashboardStats'
import { useDashboardClock } from './composables/useDashboardClock'
import { useBeileConfirmPopup } from './composables/useBeileConfirmPopup'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePerfMark } from '@/composables/usePerfMark'

const perf = usePerfMark('dashboard')

const authStore = useAuthStore()
const logoutConfirm = useConfirmDialog()
const router = useRouter()
const avatarLetter = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

const { currentTime, startClock, stopClock } = useDashboardClock()

const {
  stats,
  stockStats,
  isLoading,
  errorMessage,
  errorDetail,
  loadStats,
} = useDashboardStats()

const chartsRef = ref<InstanceType<typeof DashboardChartsSection> | null>(null)

// ===== 图表渲染：数据变化时自动更新 =====
// Vue Query SWR 后台刷新、refetchInterval 自动刷新均触发此 watch
async function renderCharts() {
  if (!stats.value || !stockStats.value) return
  await nextTick()
  try {
    await chartsRef.value?.renderOrUpdate()
  } catch (chartErr) {
    if (import.meta.env.DEV) {

      console.warn('[Dashboard] 图表渲染失败:', chartErr)
    }
  }
  perf.markMountEnd()
  perf.measureFromMount('full-interactive')
}

watch([stats, stockStats], renderCharts)

const {
  beilePopupOpen,
  beilePopupText,
  beilePopupSub,
  checkBeileConfirmPopup,
  closeBeilePopup,
  goConfirmBeileOrders,
} = useBeileConfirmPopup()

function retryLoad() {
  chartsRef.value?.resetCharts()
  loadStats().catch((err) => {
    if (import.meta.env.DEV) {

      console.error('[Dashboard] retryLoad failed:', err)
    }
  })
}

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

onMounted(async () => {
  // Vue Query 自动发起首次 fetch，无需手动调用 loadStats
  // 若 prefetch 已填充缓存，数据立即可用 → 渲染图表
  if (stats.value && stockStats.value) {
    await renderCharts()
  }
  checkBeileConfirmPopup()
  startClock()
})

onUnmounted(() => {
  stopClock()
})
</script>

<style scoped>
.dashboard {
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
