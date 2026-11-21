import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dashboardApi } from '@/api'
import { formatNumber } from '@/utils/format'
import type { MobileDashboardData } from '@/api/dashboard'
import { getErrorMessage } from '@/types/errors'

/** 移动端仪表盘数据加载与状态管理 */
export function useDashboardMobileData() {
  const loading = ref(true)
  const refreshing = ref(false)
  const error = ref<string | null>(null)
  const data = ref<MobileDashboardData | null>(null)
  const lastRefreshTime = ref<number>(0)
  const visibleCards = ref([false, false, false, false])

  // Z04-R3：动画定时器逐次覆盖旧句柄会泄漏卸载后的回调；统一收集、统一清理。
  // 原 currentTime + 10s setInterval 无任何消费方（模板未使用），是空转死代码，一并删除。
  let animTimers: ReturnType<typeof setTimeout>[] = []

  function clearAnimTimers() {
    animTimers.forEach((t) => clearTimeout(t))
    animTimers = []
  }

  onUnmounted(clearAnimTimers)

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

  /** L-22（2026-11-21 审计）：fmtNum/fmtMoney 原先自造口径（toString / ≥1万截断小数），
   *  改走 utils/format 单一真源：千分位 + 最多两位小数；空值仍显示「—」 */
  function fmtNum(n: number | null | undefined): string {
    if (n === null || n === undefined) return '—'
    return formatNumber(n)
  }

  function fmtMoney(n: number | null | undefined): string {
    if (n === null || n === undefined) return '—'
    return '¥' + formatNumber(n)
  }

  function triggerReveal() {
    clearAnimTimers()
    visibleCards.value.forEach((_, i) => {
      animTimers.push(setTimeout(() => {
        visibleCards.value = visibleCards.value.map((v, j) => j <= i ? true : v)
      }, 60 * (i + 1)))
    })
  }

  /**
   * 请求序号：右上刷新按钮、下拉刷新、错误态重试可能并发触发，
   * 没有序号时后到的旧响应会把新数据盖回去。其余移动端视图都有同款守卫，
   * 唯独仪表盘此前漏了。
   */
  let loadSeq = 0

  async function loadData() {
    const seq = ++loadSeq
    error.value = null
    try {
      const res = await dashboardApi.mobile()
      if (seq !== loadSeq) return
      data.value = res
      lastRefreshTime.value = Date.now()
    } catch (e: unknown) {
      if (seq !== loadSeq) return
      // L-22（2026-11-21 审计）：hero 区 axios 英文 message 直出（如 "Network Error"）→
      // 走 getErrorMessage 统一映射中文；非 Error 抛出物回退通用文案
      error.value = e instanceof Error ? getErrorMessage(e) : '网络请求失败'
      console.warn('[DashboardMobile] load error:', e)
    } finally {
      if (seq === loadSeq) {
        loading.value = false
        // 最新请求统一收尾：refresh() 已把卡片重置为不可见，而被抢占的旧请求不会再走
        // 上层的 triggerReveal；不补这一下会出现「数据已到、卡片永久 opacity:0」。
        if (!visibleCards.value.some(Boolean)) triggerReveal()
      }
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

  /** 下拉刷新：静默更新数据，不重置卡片入场动画，避免刷新时闪烁 */
  async function onPullRefresh() {
    if (refreshing.value) return
    refreshing.value = true
    error.value = null
    try {
      await loadData()
    } finally {
      refreshing.value = false
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
    refreshing,
    error,
    data,
    visibleCards,
    lastUpdateText,
    sortedDepartments,
    rankLabel,
    fmtNum,
    fmtMoney,
    loadData,
    refresh,
    onPullRefresh,
  }
}