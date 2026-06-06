import { onMounted, onUnmounted } from 'vue'
import { App } from '@capacitor/app'
import { Network } from '@capacitor/network'
import { StatusBar, Style } from '@capacitor/status-bar'
import { SplashScreen } from '@capacitor/splash-screen'

export function useAppLifecycle() {
  let resumeCallback: (() => void) | null = null
  let appStateListener: { remove: () => Promise<void> } | null = null
  let networkListener: { remove: () => Promise<void> } | null = null

  async function initNative() {
    try {
      await StatusBar.setStyle({ style: Style.Light })
      await SplashScreen.hide({ fadeOutDuration: 200 })
    } catch (e) {
      console.warn('[AppLifecycle] StatusBar/Splash init failed:', e)
    }
  }

  function onResume(cb: () => void) {
    resumeCallback = cb
  }

  onMounted(async () => {
    try {
      appStateListener = await App.addListener('appStateChange', (state) => {
        if (state.isActive && resumeCallback) {
          resumeCallback()
        }
      })

      networkListener = await Network.addListener('networkStatusChange', (status) => {
        if (!status.connected) {
          console.warn('[AppLifecycle] Network offline')
        }
      })

      await initNative()
    } catch (e) {
      console.warn('[AppLifecycle] Native listeners failed:', e)
    }
  })

  onUnmounted(async () => {
    resumeCallback = null
    if (appStateListener) {
      await appStateListener.remove()
      appStateListener = null
    }
    if (networkListener) {
      await networkListener.remove()
      networkListener = null
    }
  })

  return { onResume, initNative }
}
