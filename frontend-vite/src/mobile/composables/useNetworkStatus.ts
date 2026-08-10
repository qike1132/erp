/**
 * 网络状态监听 composable
 * Capacitor 环境下使用原生 Network API，Web 环境降级为 navigator.onLine
 */
import { ref, onMounted, onUnmounted } from 'vue'

export function useNetworkStatus() {
  const connected = ref(true)
  const connectionType = ref<string>('unknown')

  let networkListener: { remove: () => Promise<void> } | null = null
  let onlineHandler: (() => void) | null = null
  let offlineHandler: (() => void) | null = null

  async function init() {
    // 仅在 Capacitor 环境才尝试加载原生 Network API
    if (!import.meta.env.VITE_CAPACITOR) {
      connected.value = navigator.onLine
      onlineHandler = () => { connected.value = true }
      offlineHandler = () => { connected.value = false }
      window.addEventListener('online', onlineHandler)
      window.addEventListener('offline', offlineHandler)
      return
    }

    // Capacitor 环境：动态 import，避免 Web 构建解析失败
    try {
      const { Network } = await import('@capacitor/network')
      const status = await Network.getStatus()
      connected.value = status.connected
      connectionType.value = status.connectionType

      networkListener = await Network.addListener('networkStatusChange', (status) => {
        connected.value = status.connected
        connectionType.value = status.connectionType
      })
    } catch {
      console.warn('[useNetworkStatus] Capacitor Network API unavailable, falling back to browser')
      connected.value = navigator.onLine
      onlineHandler = () => { connected.value = true }
      offlineHandler = () => { connected.value = false }
      window.addEventListener('online', onlineHandler)
      window.addEventListener('offline', offlineHandler)
    }
  }

  onMounted(init)

  onUnmounted(async () => {
    if (networkListener) {
      await networkListener.remove()
      networkListener = null
    }
    if (onlineHandler) {
      window.removeEventListener('online', onlineHandler)
      onlineHandler = null
    }
    if (offlineHandler) {
      window.removeEventListener('offline', offlineHandler)
      offlineHandler = null
    }
  })

  return { connected, connectionType }
}
