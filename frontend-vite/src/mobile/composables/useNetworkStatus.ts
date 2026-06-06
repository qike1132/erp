import { ref, onMounted, onUnmounted } from 'vue'
import { Network } from '@capacitor/network'

export function useNetworkStatus() {
  const connected = ref(true)
  const connectionType = ref<string>('unknown')

  let networkListener: { remove: () => Promise<void> } | null = null
  let onlineHandler: (() => void) | null = null
  let offlineHandler: (() => void) | null = null

  async function init() {
    try {
      const status = await Network.getStatus()
      connected.value = status.connected
      connectionType.value = status.connectionType

      networkListener = await Network.addListener('networkStatusChange', (status) => {
        connected.value = status.connected
        connectionType.value = status.connectionType
      })
    } catch {
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
