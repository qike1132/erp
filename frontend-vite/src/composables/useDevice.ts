import { ref, readonly, onScopeDispose } from 'vue'

/**
 * 设备类型检测 composable
 * 通过 UA-CH / User-Agent / 触屏+屏幕宽度多级判断
 * 用于路由级别的 PC/移动端 UI 自动切换
 *
 * 检测优先级（高→低）：
 *   1. navigator.userAgentData.mobile（UA-CH，现代浏览器标准）
 *   2. User-Agent 正则匹配（含 iPadOS 13+ 桌面版 UA 识别）
 *   3. 触屏 + coarse pointer + 小屏幕（兜底）
 */

let _isMobile: boolean | null = null

function getUAData(): { mobile?: boolean; platform?: string } | undefined {
  if (typeof navigator === 'undefined') return undefined
  return (navigator as Navigator & { userAgentData?: { mobile?: boolean; platform?: string } }).userAgentData
}

function detectIPadOS(ua: string): boolean {
  if (typeof navigator === 'undefined') return false
  if (/iPad/i.test(ua)) return true

  const isMacUA = /Macintosh/i.test(ua)
  if (!isMacUA) return false

  const uaData = getUAData()
  if (uaData?.platform === 'iOS') return true

  const maxTouch = navigator.maxTouchPoints ?? 0
  if (maxTouch < 2) return false

  if (typeof document !== 'undefined' && 'ontouchend' in document) return true

  return false
}

function detectMobileUA(ua: string): boolean {
  if (typeof navigator === 'undefined') return false

  const uaData = getUAData()
  if (uaData?.mobile) return true

  if (/Android|iPhone|iPod|webOS|BlackBerry|IEMobile|Opera Mini|Mobile/i.test(ua)) return true
  if (detectIPadOS(ua)) return true

  return false
}

function detectTouchSmallScreen(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0
  if (!hasTouch) return false

  let isCoarsePointer = true
  if (window.matchMedia) {
    isCoarsePointer = window.matchMedia('(pointer: coarse)').matches
  }
  if (!isCoarsePointer) return false

  const screenW = window.screen?.width ?? 0
  const screenH = window.screen?.height ?? 0
  const minScreenDim = Math.min(screenW, screenH)
  const isPhoneScreen = minScreenDim <= 480 || window.innerWidth <= 768

  return isPhoneScreen
}

export function isMobileDevice(): boolean {
  if (_isMobile !== null) return _isMobile

  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    _isMobile = false
    return false
  }

  const ua = navigator.userAgent || ''
  _isMobile = detectMobileUA(ua) || detectTouchSmallScreen()
  return _isMobile
}

export function resetDeviceCache(): void {
  _isMobile = null
}

/**
 * 监听窗口大小变化，响应式更新设备类型
 * 用于支持桌面端缩放窗口切换布局的场景
 */

export function useDevice() {
  const isMobile = ref(isMobileDevice())

  if (typeof window !== 'undefined') {
    const mediaQuery = window.matchMedia('(max-width: 768px)')

    let reloadTimer: ReturnType<typeof setTimeout> | null = null
    const updateDevice = () => {
      resetDeviceCache()
      const newValue = isMobileDevice()
      if (newValue !== isMobile.value) {
        isMobile.value = newValue
        if (reloadTimer) clearTimeout(reloadTimer)
        reloadTimer = setTimeout(() => window.location.reload(), 500)
      }
    }

    mediaQuery.addEventListener('change', updateDevice)
    onScopeDispose(() => {
      mediaQuery.removeEventListener('change', updateDevice)
      if (reloadTimer) clearTimeout(reloadTimer)
    })
  }

  return {
    isMobile: readonly(isMobile),
  }
}
