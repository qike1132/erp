/**
 * App 生命周期管理 composable
 * Capacitor 环境下监听前后台切换/状态栏/启动画面，Web 环境降级为无操作
 */
import { onMounted, onUnmounted } from 'vue'

export function useAppLifecycle() {
  let resumeCallback: (() => void) | null = null
  let appStateListener: { remove: () => Promise<void> } | null = null
  let networkListener: { remove: () => Promise<void> } | null = null

  function onResume(cb: () => void) {
    resumeCallback = cb
  }

  onMounted(async () => {
    // 非 Capacitor 环境：无需原生生命周期监听
    if (!import.meta.env.VITE_CAPACITOR) return

    try {
      const [AppModule, NetworkModule, StatusBarModule, SplashModule] = await Promise.all([
        import('@capacitor/app'),
        import('@capacitor/network'),
        import('@capacitor/status-bar'),
        import('@capacitor/splash-screen'),
      ])

      appStateListener = await AppModule.App.addListener('appStateChange', (state) => {
        if (state.isActive && resumeCallback) {
          resumeCallback()
        }
      })

      networkListener = await NetworkModule.Network.addListener('networkStatusChange', (status) => {
        if (!status.connected) {
          console.warn('[AppLifecycle] Network offline')
        }
      })

      await StatusBarModule.StatusBar.setStyle({ style: StatusBarModule.Style.Light })
      await SplashModule.SplashScreen.hide({ fadeOutDuration: 200 })
    } catch (e) {
      console.warn('[AppLifecycle] Native lifecycle setup failed:', e)
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

  return { onResume }
}
