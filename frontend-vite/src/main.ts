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

import { installConsoleErrorFilter } from './utils/consoleFilter'

// 静默 Chrome 扩展导致的 runtime.lastError 噪音（精确匹配，见 consoleFilter）
installConsoleErrorFilter()

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
    // 这里的 z-index 刻意硬编码、不走 --z-error-fallback：兜底提示的出现时机就是
    // 「渲染已经出问题」，不能让它再依赖 app.css 的变量解析。10000 与令牌同值，
    // 改令牌时同步这里（zLayers.test.ts 未把 .ts 纳入裸值扫描即因为此例外）。
    el.style.cssText = 'position:fixed;top:10px;right:10px;z-index:10000;background:#fee2e2;color:#991b1b;padding:12px 16px;border-radius:8px;font-size:14px;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.15);cursor:pointer;'
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
    buster: 'binfa-erp-v13',
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

// 挂载放到 bootstrap() 末尾：PrimeVue 必须在 mount 之前安装，
// 否则窗口期内挂载的组件拿不到 $primevue 的 pt/zIndex/locale 注入，
// 表现为偶发弹层被遮罩盖住或样式裸奔。

window.addEventListener('auth:expired', async () => {
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()
  if (authStore.isLoggedIn) {
    authStore.logout()
    router.push(`/login?redirect=${encodeURIComponent(router.currentRoute.value.fullPath)}`)
  }
})

// 初始化设备特定资源；PrimeVue 安装完成后再 mount
async function bootstrap() {
  if (isMobile) {
    try {
      await import('./styles/mobile-tokens.css')
    } catch (e) {
      console.warn('[App] mobile-tokens.css 加载失败，使用默认样式', e)
    }
  } else {
    try {
      // 配置与 passthrough 样式无相互依赖，并行下载，避免挂载前多一个串行 RTT。
      const [PrimeVueMod, ptMod] = await Promise.all([
        import('primevue/config'),
        import('./styles/primevue-pt'),
      ])
      app.use(PrimeVueMod.default, {
        unstyled: true,
        pt: ptMod.plushCutePT,
        // PrimeVue 弹层(autocomplete/select/datepicker 面板等)的内联 z-index
        // 从该起点递增。项目自定义页面级弹窗用 --z-page-modal(1050)，刻意低于此处，
        // 使 PrimeVue 的下拉/抽屉能盖在其上；从这类弹窗内新开的确认框必须用
        // --z-overlay-nested/--z-modal-nested（2200/2210，均 > 此处），否则被压住
        // （BOM 联想下拉失效、明细抽屉确认框点不到的成因，见 zLayers.test.ts）。
        zIndex: { modal: 2100, overlay: 2000, menu: 2000, tooltip: 2100 },
        locale: {
          emptySearchMessage: '无匹配结果',
          searchMessage: '{0} 条结果',
        },
      })
    } catch (e) {
      console.error('[App] PrimeVue 加载失败，PC 端组件可能无法正常渲染', e)
    }
  }
  app.mount('#app')
}

bootstrap()

import('./utils/webVitals').then(({ initWebVitals }) => initWebVitals()).catch(() => {})
