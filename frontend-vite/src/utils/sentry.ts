/**
 * Sentry 初始化（生产错误遥测）。
 *
 * 为什么单独成模块：main.ts 只负责调用，DSN 解析与 PII 脱敏策略集中在此，
 * 便于单测（见 src/test/sentryInit.test.ts）。
 *
 * 用动态 import 而非顶层 import：@sentry/vue 只在配置了 DSN 时才需要，
 * 不该进 entry chunk（与 fontAwesomeLoader / echartsPreload 同一策略）。
 */
import type { App } from 'vue'

export type SentryInitOptions = {
  /** 未提供时回落 `import.meta.env.VITE_SENTRY_DSN` */
  dsn?: string
  environment?: string
  release?: string
  tracesSampleRate?: number
}

/** 默认采样率：内网自托管 ERP，不需要全量性能追踪 */
const DEFAULT_TRACES_SAMPLE_RATE = 0.05

/**
 * 初始化 Sentry。
 *
 * 未配置 DSN 时**不初始化**并返回 false —— 保持"零遥测"的既有行为，
 * 而不是进入"半配置"状态发出无意义请求。
 */
export async function initSentry(app: App, options: SentryInitOptions = {}): Promise<boolean> {
  const dsn = options.dsn ?? (import.meta.env.VITE_SENTRY_DSN as string | undefined)
  if (!dsn) return false

  const Sentry = await import('@sentry/vue')

  Sentry.init({
    app,
    dsn,
    environment: options.environment ?? (import.meta.env.MODE as string),
    release: options.release ?? (import.meta.env.VITE_APP_VERSION as string | undefined),
    tracesSampleRate: options.tracesSampleRate ?? DEFAULT_TRACES_SAMPLE_RATE,
    // 组件 props 在本项目里常是客户/业务对象（客户列表、订单…），attachProps 默认为
    // true 会把 vm.$props 作为 contexts.vue.propsData 原样送到第三方 —— 直接违反
    // 「不外送 PII」的要求，且是 beforeSend 只剥 cookies/headers 时最容易被漏掉的一条。
    attachProps: false,
    // 错误上报由本项目的 reportError 统一接管（main.ts）：若不禁用，Sentry 的
    // vueIntegration 会先报一次、再链式调用我们的处理器报第二次 → 同一异常落库两遍。
    attachErrorHandler: false,
    // 刻意**不过滤** GlobalHandlers：它同时负责 window.onerror 与
    // unhandledrejection，过滤掉会静默丢失 onerror 覆盖。重复上报改由
    // main.ts 不再自行监听 unhandledrejection 解决（单一归属）。
    beforeSend(event) {
      // 会话凭据在 cookie / Authorization 头里，绝不外送给第三方
      if (event.request) {
        delete event.request.cookies
        delete event.request.headers
      }
      // 兜底：即使将来有人把 attachProps 改回默认值，也不让组件 props 外送
      if (event.contexts) {
        delete event.contexts.vue
      }
      return event
    },
  })
  return true
}
