/**
 * 错误上报门控。
 *
 * 存在理由：main.ts 里的 `sentryReady` 开关决定了「错误到底会不会被上报」，
 * 但它原先只是 main.ts 的模块内变量 —— 任何改动（比如把
 * `initSentry(app).then(ok => { sentryReady = ok })` 改成就地丢弃结果、
 * 或删掉守卫）都能让整个遥测静默失效，而 sentryInit.test.ts 完全测不到。
 * 把这个门控抽出来单测，才守得住「错误真的会被上报」这件事本身。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { captureExceptionMock } = vi.hoisted(() => ({ captureExceptionMock: vi.fn() }))

vi.mock('@sentry/vue', () => ({
  captureException: captureExceptionMock,
  init: vi.fn(),
}))

/** 取一份**全新**的模块实例：门控用的是模块级状态，测试之间必须隔离。 */
async function freshReporter() {
  vi.resetModules()
  return await import('@/utils/errorReporter')
}

describe('errorReporter', () => {
  beforeEach(() => {
    captureExceptionMock.mockClear()
  })

  it('未标记就绪时不上报（未配置 DSN 的构建不得发出任何上报）', async () => {
    const { reportError } = await freshReporter()

    reportError(new Error('boom'))
    await Promise.resolve()

    expect(captureExceptionMock).not.toHaveBeenCalled()
  })

  it('标记就绪后上报，并透传 extra', async () => {
    const { reportError, markSentryReady } = await freshReporter()
    markSentryReady(true)

    reportError(new Error('boom'), { info: 'render' })

    await vi.waitFor(() => expect(captureExceptionMock).toHaveBeenCalledTimes(1))
    expect(captureExceptionMock.mock.calls[0]?.[1]).toEqual({ extra: { info: 'render' } })
  })

  it('超出上限后停止上报（上限必须对同步突发也生效）', async () => {
    const { reportError, markSentryReady } = await freshReporter()
    markSentryReady(true)

    // 同步连发 15 次：若把计数放进 Promise 回调里，突发会全部通过守卫
    for (let i = 0; i < 15; i++) reportError(new Error(`e${i}`))

    await vi.waitFor(() => expect(captureExceptionMock).toHaveBeenCalledTimes(10))
    // 再等一拍，确认没有第 11 条迟到
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(captureExceptionMock).toHaveBeenCalledTimes(10)
  })

  it('就绪状态可被撤销（初始化失败时不得继续上报）', async () => {
    const { reportError, markSentryReady } = await freshReporter()
    markSentryReady(true)
    markSentryReady(false)

    reportError(new Error('boom'))
    await Promise.resolve()

    expect(captureExceptionMock).not.toHaveBeenCalled()
  })
})
