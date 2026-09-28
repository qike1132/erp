import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { queryClient, queryPersister, shouldPersistQuery } from './utils/queryClient'
import { FontAwesomeIconLazy } from './components/icon/FontAwesomeIconLazy'
import './styles/app.css'
import App from './App.vue'
import router from './router'
import { isMobileDevice } from './composables/useDevice'
import { devLog } from './utils/devLog'
import { initSentry } from './utils/sentry'
import { markSentryReady, reportError } from './utils/errorReporter'

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

app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', info, err)
  reportError(err, { info })
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
  // 仅开发期可见（生产构建会 drop 掉 console）。
  // 上报交给 Sentry 的 GlobalHandlers 集成 —— 它同时覆盖 window.onerror，
  // 因此这里不再自行 reportError，否则同一拒绝会落库两遍。
  console.error('[Unhandled Rejection]', event.reason)
})

app.use(createPinia())
app.use(router)
// 懒加载版全局注册：图标首次出现时按需动态 import，避免全量 solid 图标进首屏
app.component('FontAwesomeIcon', FontAwesomeIconLazy)
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

// 生产错误遥测：尽早初始化，缩小「挂载期间出错无人知晓」的窗口。
// 未配置 VITE_SENTRY_DSN 时不会初始化，reportError 退化为 no-op
// （等价于修复前行为，但不会再让人误以为"有监控"）。
initSentry(app)
  .then((ok) => markSentryReady(ok))
  .catch(() => { /* 遥测初始化失败不得影响启动 */ })

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
            // PrimeVue 弹层(autocomplete/select/datepicker 面板等)的内联 z-index
            // 从该起点递增。项目自定义弹窗(pd-overlay 等)硬编码 z-index: 1050,
            // 默认 overlay 起点 1000 会被弹窗遮罩盖住 —— 弹窗内打开联想下拉
            // 表现为"面板已渲染但不可见"(BOM 配置联想失效成因,2026-09-11 修复)。
            zIndex: { modal: 2100, overlay: 2000, menu: 2000, tooltip: 2100 },
            locale: {
              emptySearchMessage: '无匹配结果',
              searchMessage: '{0} 条结果',
            },
          })
        })
      )
      .catch((e) => console.error('[App] PrimeVue 加载失败，PC 端组件可能无法正常渲染', e))
  }
}

bootstrap()

import('./utils/webVitals').then(({ initWebVitals }) => initWebVitals()).catch(() => {})
