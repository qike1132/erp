import { ref, onMounted, onUnmounted, reactive } from 'vue'

export function useAutoRefresh(callback: () => Promise<void>, intervalMs = 30000) {
  const enabled = ref(true)
  let timer: ReturnType<typeof setInterval> | null = null

  function runOnce() {
    if (document.hidden || !enabled.value) return
    callback().catch(() => { /* silent */ })
  }

  function start() {
    if (timer) return
    timer = setInterval(runOnce, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  /**
   * 重置轮询计时器（debounce）。
   * 当 WebSocket 推送已触发即时刷新后调用，可避免轮询周期内的重复刷新。
   */
  function resetTimer() {
    if (!timer) return
    clearInterval(timer)
    timer = setInterval(runOnce, intervalMs)
  }

  onMounted(start)
  onUnmounted(stop)

  return reactive({ enabled, start, stop, resetTimer })
}
