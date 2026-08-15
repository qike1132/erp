/**
 * useDashboardAutoRefresh — 仪表盘自动刷新 Hook
 *
 * 每 30 秒触发一次刷新回调，确保"今日备货/今日出货/待审批/待备料"
 * 等模块实时显示。逻辑自 DashboardView.vue 原样搬移；
 * 启动/停止由组件生命周期接线（onUnmounted 清理 refreshTimer）。
 */
export function useDashboardAutoRefresh(onTick: () => void) {
  let refreshTimer: ReturnType<typeof setInterval> | null = null

  /** 启动自动刷新（每 30 秒） */
  function startAutoRefresh() {
    refreshTimer = setInterval(() => {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.log('[Dashboard] 自动刷新数据...')
      }
      onTick()
    }, 30 * 1000)
  }

  /** 停止自动刷新并清理定时器（组件卸载时调用） */
  function stopAutoRefresh() {
    if (refreshTimer) {
      clearInterval(refreshTimer)
      refreshTimer = null
    }
  }

  return {
    startAutoRefresh,
    stopAutoRefresh,
  }
}
