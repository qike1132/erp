/**
 * 错误上报门控（是否真的把错误送到 Sentry）。
 *
 * 与 `utils/sentry.ts` 的分工：那边负责「怎么初始化」，这边负责「什么时候上报」。
 * 拆出来是为了可测 —— 门控一旦失效，整个遥测会静默变成 no-op，
 * 而那正是本次修复要消灭的状态（见 src/test/errorReporter.test.ts）。
 */

/** 单会话最多上报多少条：防止某个渲染错误每帧刷屏把配额打满。 */
const MAX_REPORTS = 10

let ready = false
let reports = 0

/**
 * 缓存的 `@sentry/vue` 动态 import。
 *
 * 只取一次并复用同一个 promise：突发错误时若每次都发新的 `import()`，
 * 并发解析同一个 mock/模块在测试环境下会让后续回调抛错（被 catch 吞掉 →
 * 静默丢上报）。缓存起来既避开该问题，也少一次模块解析。
 */
let sentryModule: Promise<typeof import('@sentry/vue')> | null = null

function loadSentry(): Promise<typeof import('@sentry/vue')> {
  sentryModule ??= import('@sentry/vue').catch((error: unknown) => {
    // 失败**不缓存**：否则一次 chunk 加载失败会让整个会话永久静默无遥测。
    sentryModule = null
    throw error
  })
  return sentryModule
}

/** 由 `initSentry()` 的结果驱动；未就绪时 reportError 是 no-op。 */
export function markSentryReady(isReady: boolean): void {
  ready = isReady
}

export function isSentryReady(): boolean {
  return ready
}

/**
 * 上报一个错误。未就绪 / 超上限时直接返回，**且不加载 Sentry chunk**。
 *
 * 计数在守卫处同步自增（而不是等 `import()` 落地后）：上限的意义是限制
 * **上报量**，同步计数才能对「一次性抛出十几个错误」的突发真正生效。
 */
export function reportError(error: unknown, extra?: Record<string, unknown>): void {
  if (!ready || reports >= MAX_REPORTS) return
  reports += 1

  void loadSentry()
    .then(({ captureException }) => captureException(error as Error, extra ? { extra } : undefined))
    .catch(() => { /* 遥测失败不得影响业务 */ })
}
