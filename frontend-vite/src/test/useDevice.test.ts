import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

describe('useDevice', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  async function loadModule() {
    const mod = await import('../composables/useDevice')
    return mod
  }

  it('SSR 环境（无 window/navigator）返回 false', async () => {
    vi.stubGlobal('window', undefined)
    vi.stubGlobal('navigator', undefined)
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('iPhone UA 判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      platform: 'iPhone',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 390,
      screen: { width: 390, height: 844 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('Android UA 判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 412,
      screen: { width: 412, height: 915 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('iPadOS 13+ 桌面版 UA 通过 maxTouchPoints≥2 + ontouchend 识别', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15',
      platform: 'MacIntel',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 1024,
      screen: { width: 1024, height: 1366 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('Mac Touch Bar（maxTouchPoints=1）不误判为 iPad', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      platform: 'MacIntel',
      maxTouchPoints: 1,
    })
    vi.stubGlobal('window', {
      innerWidth: 1440,
      screen: { width: 1440, height: 900 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('Mac 桌面（无触屏）不误判为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
      platform: 'MacIntel',
      maxTouchPoints: 0,
    })
    vi.stubGlobal('window', {
      innerWidth: 1920,
      screen: { width: 1920, height: 1080 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('Surface Pro（触屏+宽屏+精细指针）不误判为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
      platform: 'Win32',
      maxTouchPoints: 10,
    })
    vi.stubGlobal('window', {
      innerWidth: 950,
      devicePixelRatio: 1.5,
      screen: { width: 2736, height: 1824 },
      matchMedia: (q: string) => ({
        matches: q.includes('fine'),
        addEventListener: () => {},
      }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('桌面 Chrome（无触屏）判定为 PC 端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
      platform: 'Win32',
      maxTouchPoints: 0,
    })
    vi.stubGlobal('window', {
      innerWidth: 1920,
      screen: { width: 1920, height: 1080 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('Capacitor 已摘除：桌面 Chrome（无触屏）不再强制移动端', async () => {
    vi.stubEnv('VITE_CAPACITOR', '1')
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
      platform: 'Win32',
      maxTouchPoints: 0,
    })
    vi.stubGlobal('window', {
      innerWidth: 1920,
      screen: { width: 1920, height: 1080 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    // VITE_CAPACITOR 已不再参与设备判定（2026-08-31 摘除 Capacitor 全链路）
    expect(isMobileDevice()).toBe(false)
  })

  it('UA-CH userAgentData.mobile=true 判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
      userAgentData: { mobile: true, platform: 'Android' },
    })
    vi.stubGlobal('window', {
      innerWidth: 360,
      screen: { width: 360, height: 800 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('UA-CH userAgentData.platform=iOS 判定为 iPad', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15',
      platform: 'MacIntel',
      maxTouchPoints: 5,
      userAgentData: { mobile: false, platform: 'iOS' },
    })
    vi.stubGlobal('window', {
      innerWidth: 1024,
      screen: { width: 1024, height: 1366 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('iPhone 横屏（screen.width > 768）通过 UA 正则仍判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
      platform: 'iPhone',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 844,
      screen: { width: 844, height: 390 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('resetDeviceCache 后重新计算', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 390,
      screen: { width: 390, height: 844 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice, resetDeviceCache } = await loadModule()
    expect(isMobileDevice()).toBe(true)

    resetDeviceCache()
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
      platform: 'Win32',
      maxTouchPoints: 0,
    })
    vi.stubGlobal('window', {
      innerWidth: 1920,
      screen: { width: 1920, height: 1080 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    expect(isMobileDevice()).toBe(false)
  })

  it('检测结果被缓存，重复调用不重新计算', async () => {
    const uaGetter = vi.fn(() => 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)')
    vi.stubGlobal('navigator', {
      get userAgent() { return uaGetter() },
      platform: 'iPhone',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 390,
      screen: { width: 390, height: 844 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', { ontouchend: true })
    const { isMobileDevice } = await loadModule()
    isMobileDevice()
    isMobileDevice()
    isMobileDevice()
    expect(uaGetter).toHaveBeenCalledTimes(1)
  })

  it('Chrome 隐私模式 UA 简化（无 Mobile 关键词）+ 触屏小屏 → 通过 detectTouchSmallScreen 判定', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 360,
      screen: { width: 360, height: 800 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('Android WebView（含 wv 标记）判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 412,
      screen: { width: 412, height: 915 },
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('折叠屏展开态（内屏宽度 > 768）通过 Android UA 正则仍判定为移动端', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 14; SM-F946B) AppleWebKit/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 1080,
      screen: { width: 1080, height: 2316 },
      matchMedia: (q: string) => ({
        matches: q.includes('coarse'),
        addEventListener: () => {},
      }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })

  it('navigator.userAgentData 不存在时不崩溃', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.B (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
      platform: 'Win32',
      maxTouchPoints: 0,
    })
    vi.stubGlobal('window', {
      innerWidth: 1920,
      screen: { width: 1920, height: 1080 },
      matchMedia: () => ({ matches: false, addEventListener: () => {} }),
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(false)
  })

  it('window.screen 不存在时回退到 innerWidth', async () => {
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
      platform: 'Linux armv8l',
      maxTouchPoints: 5,
    })
    vi.stubGlobal('window', {
      innerWidth: 400,
      matchMedia: () => ({ matches: true, addEventListener: () => {} }),
      ontouchstart: true,
    })
    vi.stubGlobal('document', {})
    const { isMobileDevice } = await loadModule()
    expect(isMobileDevice()).toBe(true)
  })
})
