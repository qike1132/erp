import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dashboardApi } from '@/api'
import type { MobileDashboardData } from '@/api/dashboard'

/** 移动端仪表盘数据加载与状态管理 */
export function useDashboardMobileData() {
  const loading = ref(true)
  const error = ref<string | null>(null)
  const data = ref<MobileDashboardData | null>(null)
  const lastRefreshTime = ref<number>(0)
  const visibleCards = ref([false, false, false, false])

  let timeTimer: ReturnType<typeof setInterval> | null = null
  let animTimer: ReturnType<typeof setTimeout> | null = null

  const currentTime = ref('')
  function updateTime() {
    const now = new Date()
    currentTime.value = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0')
  }
  updateTime()
  timeTimer = setInterval(updateTime, 10000)

  onUnmounted(() => {
    if (timeTimer) clearInterval(timeTimer)
    if (animTimer) clearTimeout(animTimer)
  })

  const lastUpdateText = computed(() => {
    if (loading.value) return '加载中...'
    if (error.value) return `加载失败: ${error.value}`
    if (lastRefreshTime.value === 0) return '加载中...'
    const d = new Date(lastRefreshTime.value)
    return '最后更新: ' + String(d.getHours()).padStart(2, '0') + ':' +
      String(d.getMinutes()).padStart(2, '0') + ':' +
      String(d.getSeconds()).padStart(2, '0')
  })

  const sortedDepartments = computed(() => {
    if (!data.value?.production?.departments) return []
    return [...data.value.production.departments].sort((a, b) => b.output_value - a.output_value)
  })

  function rankLabel(idx: number): string {
    return idx < 3 ? (['#1', '#2', '#3'][idx] ?? '') : '#' + (idx + 1)
  }

  function rankClass(idx: number): string {
    return idx === 0 ? 'm-rank-1' : 'm-rank-other'
  }

  function fmtNum(n: number | null | undefined): string {
    if (n === null || n === undefined) return '—'
    return n.toString()
  }

  function fmtMoney(n: number | null | undefined): string {
    if (n === null || n === undefined) return '—'
    if (n >= 10000) return '¥' + Math.floor(n).toString()
    return '¥' + n.toFixed(2)
  }

  function triggerReveal() {
    visibleCards.value.forEach((_, i) => {
      animTimer = setTimeout(() => {
        visibleCards.value = visibleCards.value.map((v, j) => j <= i ? true : v)
      }, 60 * (i + 1))
    })
  }

  async function loadData() {
    error.value = null
    try {
      data.value = await dashboardApi.mobile()
      lastRefreshTime.value = Date.now()
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '网络请求失败'
      console.warn('[DashboardMobile] load error:', e)
    } finally {
      loading.value = false
    }
  }

  async function refresh() {
    loading.value = true
    error.value = null
    visibleCards.value = [false, false, false, false]
    await loadData()
    if (!loading.value) {
      triggerReveal()
    }
  }

  onMounted(async () => {
    await loadData()
    if (!loading.value) {
      triggerReveal()
    }
  })

  return {
    loading,
    error,
    data,
    visibleCards,
    currentTime,
    lastUpdateText,
    sortedDepartments,
    rankLabel,
    rankClass,
    fmtNum,
    fmtMoney,
    loadData,
    refresh,
  }
}