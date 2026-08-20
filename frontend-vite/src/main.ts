import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { queryClient, queryPersister, shouldPersistQuery } from './utils/queryClient'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import './styles/app.css'
import './icons'
import App from './App.vue'
import router from './router'
import { initTokenCache } from './utils/secureStorage'
import { isMobileDevice } from './composables/useDevice'
import { devLog } from './utils/devLog'

// 静默 Chrome 扩展导致的 runtime.lastError 噪音
// 根因：Manifest V3 扩展的 content script 向已休眠的 background service worker
// 发送消息时，消息端口已被关闭。这不是应用代码的问题。
{
  const _origError = console.error.bind(console)
  const SUPPRESS_PATTERNS = [
    'message port closed before a response was received',
    'Could not establish connection. Receiving end does not exist',
  ]
  console.error = (...args: unknown[]) => {
    const firstArg = args[0]
    if (typeof firstArg === 'string' && SUPPRESS_PATTERNS.some((p) => firstArg.includes(p))) {
      return
    }
    _origError(...args)
  }
}

const app = createApp(App)
const isMobile = isMobileDevice()

if (import.meta.env.DEV) {
  devLog(`[App] 启动模式: ${isMobile ? '移动端 UI' : 'PC端 UI'}`)

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then((regs) => {
      if (regs.length > 0) {
        console.warn(`[App] 检测到 ${regs.length} 个残留 Service Worker，开发模式下自动注销`)
        regs.forEach((reg) => reg.unregister().then(() => devLog('[App] Service Worker 已注销:', reg.scope)))
      }
    }).catch(() => {})
  }
}

let sentryErrorCount = 0
const MAX_SENTRY_REPORTS = 10

app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', info, err)
  if (sentryErrorCount < MAX_SENTRY_REPORTS) {
    sentryErrorCount++
    try {
      import('@sentry/vue').then(({ captureException }) => captureException(err as Error, { extra: { info } })).catch(() => {})
    } catch { /* noop */ }
  }
  if (!document.getElementById('app-error-fallback')) {
    const el = document.createElement('div')
    el.id = 'app-error-fallback'
    el.style.cssText = 'position:fixed;top:10px;right:10px;z-index:99999;background:#fee2e2;color:#991b1b;padding:12px 16px;border-radius:8px;font-size:14px;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.15);cursor:pointer;'
    el.textContent = '页面渲染出现异常，请刷新页面重试'
    el.onclick = () => { el.remove(); location.reload() }
    document.body.appendChild(el)
    setTimeout(() => el.remove(), 10000)
  }
}

window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason)
})

app.use(createPinia())
app.use(router)
app.component('FontAwesomeIcon', FontAwesomeIcon)
app.use(VueQueryPlugin, { queryClient })

// ===== Vue Query 缓存持久化（sessionStorage）=====
// 组件级 SWR 缓存（staleTime）只在本会话生效：F5 刷新/重新登录后内存缓存清空，
// 所有页面需重新加载。这里把查询缓存持久化到 sessionStorage（官方 persistQueryClient）：
// - 刷新后恢复缓存 → 页面先渲染缓存数据（秒开），超过 staleTime 的查询挂载后后台静默刷新
// - buster 版本号：前端数据结构变更时自动清空旧缓存，避免新旧数据错位
if (queryPersister) {
  // persistQueryClient 返回 [unsubscribe, restorePromise]：await 第二项等待
  // 缓存恢复完成，此后 cache 变更会持续写盘（含 throttle 节流）
  const [, restorePromise] = persistQueryClient({
    queryClient,
    persister: queryPersister,
    buster: 'binfa-erp-v1',
    // 24h 上限；sessionStorage 随标签页关闭自动清除
    maxAge: 1000 * 60 * 60 * 24,
    // 实时任务、用户/权限、审计流水不落盘；普通列表/报表继续享受跨刷新 SWR。
    dehydrateOptions: {
      shouldDehydrateQuery: (query) => shouldPersistQuery(query.queryKey),
    },
  })
  void restorePromise.catch(() => {
    console.warn('[QueryCache] 持久化缓存恢复失败，已自动丢弃旧缓存')
  })
}

// 尽快挂载应用，不阻塞在 PrimeVue / 图标 / Token 缓存等异步初始化上
app.mount('#app')

window.addEventListener('auth:expired', async () => {
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()
  if (authStore.isLoggedIn) {
    authStore.logout()
    router.push(`/login?redirect=${encodeURIComponent(router.currentRoute.value.fullPath)}`)
  }
})

// 异步初始化：设备特定资源，不阻塞首次渲染
async function bootstrap() {
  if (isMobile) {
    try {
      await import('./styles/mobile-tokens.css')
    } catch (e) {
      console.warn('[App] mobile-tokens.css 加载失败，使用默认样式', e)
    }
  } else {
    // PrimeVue 配置在 mount 后异步安装（Vue 3 支持运行时 install plugin）
    import('primevue/config')
      .then((PrimeVueMod) =>
        import('./styles/primevue-pt').then((ptMod) => {
          app.use(PrimeVueMod.default, {
            unstyled: true,
            pt: ptMod.plushCutePT,
            locale: {
              emptySearchMessage: '无匹配结果',
              searchMessage: '{0} 条结果',
            },
          })
        })
      )
      .catch((e) => console.error('[App] PrimeVue 加载失败，PC 端组件可能无法正常渲染', e))
  }

  // FontAwesome CSS 异步加载（<i class="fas fa-xxx"> 方式渲染的图标依赖此 CSS）
  // P1-02 修复：使用动态 import 避免阻塞首屏渲染，sidebar 挂载时 CSS 已完成加载
  import('@fortawesome/fontawesome-free/css/all.min.css').catch((e) =>
    console.warn('[App] FontAwesome CSS 加载失败，侧边栏图标可能无法显示', e),
  )

  // Token 缓存初始化独立执行，不阻塞渲染
  initTokenCache().catch(() => {})
}

bootstrap()

import('./utils/webVitals').then(({ initWebVitals }) => initWebVitals()).catch(() => {})
