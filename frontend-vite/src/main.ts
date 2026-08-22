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

/**
 * 检测"陈旧缓存导致的动态 chunk 加载失败"。
 *
 * 根因：PWA Service Worker 的 precache 缓存了旧的 index.html 与旧 chunk。
 * 每次构建 JS 文件 hash 名变化后，已运行的旧页面仍引用已被清理的旧 chunk，
 * SPA 导航到懒加载页面时触发 Failed to fetch dynamically imported module。
 * 此时页面本身无 bug，只是缓存陈旧——应自动自愈而非让用户看到"渲染异常"死胡同。
 */
const CHUNK_ERROR_PATTERNS = [
  /Failed to fetch dynamically imported module/i,
  /Unable to preload CSS/i,
  /Error loading dynamically imported module/i,
  /Importing a module script failed/i,
  /Loading chunk/i,
  /ChunkLoadError/i,
  /Loading .* chunk .* failed/i,
]

function isChunkLoadError(value: unknown): boolean {
  if (value instanceof Error) {
    return CHUNK_ERROR_PATTERNS.some((re) => re.test(value.message))
  }
  if (typeof value === 'string') {
    return CHUNK_ERROR_PATTERNS.some((re) => re.test(value))
  }
  return false
}

let _chunkRecoveryTimer: ReturnType<typeof setTimeout> | null = null

// 自愈收敛计数：单次 reload 仍可能被仍然控制的陈旧 SW 再次喂回旧 shell，
// 因此在时间窗内允许多次自愈，直到装上新版本；超过上限即停止，避免死循环。
// 与 router/index.ts 的路由级 chunk 重试逻辑保持一致。
const RECOVER_KEY = '__app_recover_count'
const RECOVER_TS_KEY = '__app_recover_ts'
const MAX_RECOVER = 3
// 计数有效期：超时后重置，避免服务端恢复后用户因历史计数被永久卡死
const RECOVER_WINDOW_MS = 60_000

function shouldRecover(): boolean {
  const lastTs = Number(sessionStorage.getItem(RECOVER_TS_KEY) || 0)
  let count = Number(sessionStorage.getItem(RECOVER_KEY) || 0)
  if (!lastTs || Date.now() - lastTs > RECOVER_WINDOW_MS) count = 0
  count += 1
  sessionStorage.setItem(RECOVER_KEY, String(count))
  sessionStorage.setItem(RECOVER_TS_KEY, String(Date.now()))
  return count <= MAX_RECOVER
}

/** 陈旧缓存自愈：注销旧 SW + 清缓存 + 强制重载，多次重载直到装上新版本 */
async function recoverFromStaleCache(): Promise<boolean> {
  if (!shouldRecover()) return false
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations()
      await Promise.all(regs.map((reg) => reg.unregister()))
    }
    if (typeof caches !== 'undefined') {
      const keys = await caches.keys()
      await Promise.all(keys.map((key) => caches.delete(key)))
    }
  } catch (e) {
    console.warn('[App] 陈旧缓存清理失败，直接重载', e)
  }
  location.reload()
  return true
}

/** 触发自愈（防抖，避免导航时连续触发多次 reload） */
function triggerChunkRecovery() {
  if (_chunkRecoveryTimer) return
  _chunkRecoveryTimer = setTimeout(() => {
    _chunkRecoveryTimer = null
    void recoverFromStaleCache()
  }, 300)
}

// 非 chunk 渲染错误的一次性自愈标记：仅在首次错误时空上触发一次，
// 避免掩盖持续存在的真实 bug（真实 bug 会在 reload 后复现并被计数上限拦截）。
let _genericSelfHealOnce = false

app.config.errorHandler = (err, _instance, info) => {
  if (isChunkLoadError(err)) {
    console.error('[Vue Error] 动态模块加载失败(疑似陈旧SW缓存)，正在自动自愈', info, err)
    triggerChunkRecovery()
    return
  }
  console.error('[Vue Error]', info, err)
  // 非 chunk 的渲染错误：若属于“首次进入某页面才报错、手动刷新即恢复”的场景
  // （常由 SW 陈旧缓存/被清理的旧 chunk 间接引起），也自动自愈一次，免去手动刷新。
  if (!_genericSelfHealOnce) {
    _genericSelfHealOnce = true
    void recoverFromStaleCache()
  }
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
  if (isChunkLoadError(event.reason)) {
    triggerChunkRecovery()
  }
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


  // Token 缓存初始化独立执行，不阻塞渲染
  initTokenCache().catch(() => {})
}

bootstrap()

import('./utils/webVitals').then(({ initWebVitals }) => initWebVitals()).catch(() => {})
