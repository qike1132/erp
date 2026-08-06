import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { VueQueryPlugin } from '@tanstack/vue-query'
import './styles/app.css'
import './styles/mobile-tokens.css'

import App from './App.vue'
import router from './router'
import { initTokenCache } from './utils/secureStorage'
import { plushCutePT } from './styles/primevue-pt'

const app = createApp(App)

const MAX_ERROR_REPORTS = 10
let errorCount = 0

app.config.errorHandler = (err, _instance, info) => {
  errorCount++
  console.error('[Vue Error]', info, err)

  // 前 N 个错误上报 Sentry（避免雪崩）
  if (errorCount <= MAX_ERROR_REPORTS) {
    try {
      // @ts-expect-error Sentry 可选依赖，未安装时静默失败
      import('@sentry/vue').then(({ captureException }: { captureException: (err: unknown, ctx?: Record<string, unknown>) => void }) => {
        captureException(err, { extra: { info } })
      }).catch(() => { /* Sentry 未配置时静默 */ })
    } catch { /* noop */ }
  }

  // 降级 UI：确保页面不白屏
  const errorContainer = document.getElementById('app-error-fallback')
  if (!errorContainer && errorCount <= 3) {
    const el = document.createElement('div')
    el.id = 'app-error-fallback'
    el.style.cssText = 'position:fixed;top:10px;right:10px;z-index:99999;background:#fee2e2;color:#991b1b;padding:12px 16px;border-radius:8px;font-size:14px;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.15);cursor:pointer;'
    el.textContent = '页面渲染出现异常，请刷新页面重试'
    el.onclick = () => { el.remove(); location.reload() }
    document.body.appendChild(el)
    setTimeout(() => el.remove(), 10000)
  }
}

// 未捕获的 Promise 错误全局兜底
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Unhandled Rejection]', event.reason)
})

app.use(createPinia())
app.use(PrimeVue, {
  unstyled: true,
  pt: plushCutePT,
  locale: {
    emptySearchMessage: '无匹配结果',
    searchMessage: '{0} 条结果',
  },
})
app.use(router)
app.use(VueQueryPlugin, {
  queryClientConfig: {
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (failureCount, error) => {
          // 401 不重试，避免 token 过期时产生大量无效请求
          if ((error as { response?: { status?: number } })?.response?.status === 401) return false
          return failureCount < 1
        },
        refetchOnWindowFocus: false,
      },
    },
  },
})

// Capacitor 环境下先从 SecureStorage 加载 token 到缓存，再挂载应用
// Web 环境下 initTokenCache() 立即返回，不影响启动速度
initTokenCache().finally(() => app.mount('#app'))

import('./utils/webVitals').then(({ initWebVitals }) => initWebVitals())

// FontAwesome 图标延后加载：避免 150+ 图标注册阻塞首屏渲染
// dom.watch() 会在加载完成后自动扫描 DOM 并替换 <i class="fas fa-*"> 占位符
import('./icons').catch((e) => console.warn('[icons] lazy load failed:', e))
