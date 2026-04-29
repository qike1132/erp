import { ref, onMounted, onUnmounted, reactive } from 'vue'

export function useAutoRefresh(callback: () => Promise<void>, intervalMs = 30000) {
  const enabled = ref(true)
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    if (timer) return
    timer = setInterval(async () => {
      if (document.hidden || !enabled.value) return
      try {
        await callback()
      } catch {
        /* silent */
      }
    }, intervalMs)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(start)
  onUnmounted(stop)

  return reactive({ enabled, start, stop })
}
