/**
 * Sentry 初始化守卫。
 *
 * 背景（上线前审计）：main.ts 里 `captureException` 一直在调，但**全仓没有 Sentry.init()**，
 * 于是所有前端错误上报都是 no-op —— 生产环境等于没有错误遥测，而且 `console.error` 还被
 * 生产构建的 esbuild.drop 剥离，连本地日志都没有。
 *
 * 本文件锁两件事：
 * 1) 未配置 DSN 时**不得**初始化（避免半配置状态发出无意义请求）；
 * 2) 配置了 DSN 时必须带 PII 脱敏的 beforeSend（不入库 cookies / headers）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { initMock } = vi.hoisted(() => ({ initMock: vi.fn() }))

vi.mock('@sentry/vue', () => ({
  init: initMock,
  captureException: vi.fn(),
}))

import { initSentry } from '@/utils/sentry'

const APP_STUB = {} as never

/** beforeSend 收到的事件的最小形状（只声明断言用到的字段）。 */
type SentryEventLike = {
  message?: string
  request?: { cookies?: unknown; headers?: unknown; url?: string }
  contexts?: { vue?: unknown; other?: unknown }
}

/** 捕获到的 Sentry.init 入参（只声明断言用到的字段）。 */
type CapturedInitOptions = {
  app?: unknown
  dsn?: string
  attachProps?: boolean
  attachErrorHandler?: boolean
  tracesSampleRate?: number
  integrations?: (defaults: Array<{ name: string }>) => Array<{ name: string }>
  beforeSend?: (event: SentryEventLike) => SentryEventLike
}

/** 取最近一次 Sentry.init 的入参（未被调用则直接失败，避免断言打在 undefined 上）。 */
function lastInitOptions(): CapturedInitOptions {
  const call = initMock.mock.calls.at(-1)
  if (!call) throw new Error('Sentry.init 未被调用')
  return call[0] as CapturedInitOptions
}

function lastBeforeSend(): (event: SentryEventLike) => SentryEventLike {
  const { beforeSend } = lastInitOptions()
  if (!beforeSend) throw new Error('Sentry.init 未提供 beforeSend')
  return beforeSend
}

describe('initSentry', () => {
  beforeEach(() => {
    initMock.mockClear()
  })

  it('未提供 DSN 时不初始化，返回 false', async () => {
    expect(await initSentry(APP_STUB, { dsn: '' })).toBe(false)
    expect(initMock).not.toHaveBeenCalled()
  })

  it('提供 DSN 时初始化并返回 true，且把 app 与 dsn 透传', async () => {
    const ok = await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })

    expect(ok).toBe(true)
    expect(initMock).toHaveBeenCalledTimes(1)
    const options = lastInitOptions()
    expect(options.app).toBe(APP_STUB)
    expect(options.dsn).toBe('https://abc@sentry.example.com/1')
  })

  it('beforeSend 剥掉 cookies 与 headers（不把会话凭据送到第三方）', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })
    const beforeSend = lastBeforeSend()

    const event = {
      request: { cookies: { access_token: 'SECRET' }, headers: { Authorization: 'Bearer SECRET' }, url: 'https://x/' },
    }
    const out = beforeSend(event)

    // 原地修改并返回同一对象（断言打在本地变量上，避免可选字段的类型噪音）
    expect(out).toBe(event)
    expect(event.request.cookies).toBeUndefined()
    expect(event.request.headers).toBeUndefined()
    // 非敏感字段保留，否则事件失去定位价值
    expect(event.request.url).toBe('https://x/')
  })

  it('beforeSend 对没有 request 的事件不抛错', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })
    const beforeSend = lastBeforeSend()

    expect(() => beforeSend({ message: 'boom' })).not.toThrow()
    expect(beforeSend({ message: 'boom' }).message).toBe('boom')
  })

  it('关闭 attachProps：组件 props 常是客户/业务对象，绝不能外送', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })

    // @sentry/vue 默认 attachProps=true，会把 vm.$props 作为 contexts.vue.propsData 上报
    expect(lastInitOptions().attachProps).toBe(false)
  })

  it('beforeSend 兜底剥掉 contexts.vue（防集成变更后 props 再次外送）', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })
    const beforeSend = lastBeforeSend()

    const event = { contexts: { vue: { propsData: { customers: ['张三'] } }, other: { a: 1 } } }
    const out = beforeSend(event)

    expect(out).toBe(event)
    expect(event.contexts.vue).toBeUndefined()
    expect(event.contexts.other).toEqual({ a: 1 })
  })

  it('接管 Vue 错误上报：关闭 Sentry 自带的 Vue 错误处理器', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })

    // 否则 Sentry 的 vueIntegration 会先报一次，再链式调用我们的处理器报第二次
    expect(lastInitOptions().attachErrorHandler).toBe(false)
  })

  it('保留 Sentry 的 GlobalHandlers（它同时负责 window.onerror 与 unhandledrejection）', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })

    // 过滤掉 GlobalHandlers 会**静默丢掉 window.onerror 覆盖**；重复上报改由
    // main.ts 不再自行监听 unhandledrejection 解决（见 main.ts）。
    expect(lastInitOptions().integrations).toBeUndefined()
  })

  it('tracesSampleRate 落在 (0, 0.2]，避免把内网流量全量上报', async () => {
    await initSentry(APP_STUB, { dsn: 'https://abc@sentry.example.com/1' })
    const { tracesSampleRate } = lastInitOptions()

    expect(tracesSampleRate).toBeGreaterThan(0)
    expect(tracesSampleRate).toBeLessThanOrEqual(0.2)
  })
})
