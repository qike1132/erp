/**
 * useDashboardClock — 仪表盘工具栏时钟 Hook
 *
 * 每分钟刷新一次当前时间（yyyy/MM/dd HH:mm）。
 * 逻辑自 DashboardView.vue 原样搬移；启动/停止由组件生命周期接线。
 */
import { ref } from 'vue'

export function useDashboardClock() {
  /** 工具栏展示的当前时间 */
  const currentTime = ref('')

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

  /** 启动时钟：立即更新一次，此后每 60 秒刷新 */
  function startClock() {
    updateTime()
    clockTimer = setInterval(updateTime, 60_000)
  }

  /** 停止时钟并清理定时器（组件卸载时调用） */
  function stopClock() {
    if (clockTimer) {
      clearInterval(clockTimer)
      clockTimer = null
    }
  }

  return {
    currentTime,
    updateTime,
    startClock,
    stopClock,
  }
}
