/**
 * chunk 加载失败时不得让遥测永久静默。
 *
 * 背景：`errorReporter` 缓存 `@sentry/vue` 的动态 import 以避免并发解析问题。
 * 若把**失败的** promise 也缓存下来，一次网络抖动就会让整个会话再也无法上报 ——
 * 而这正是本次修复要消灭的状态（静默无遥测）。
 */
import { describe, it, expect, vi } from 'vitest'

const { attempts } = vi.hoisted(() => ({ attempts: { count: 0 } }))

vi.mock('@sentry/vue', () => {
  attempts.count += 1
  throw new Error('chunk load failed')
})

import { reportError, markSentryReady } from '@/utils/errorReporter'

const tick = () => new Promise((resolve) => setTimeout(resolve, 10))

describe('errorReporter：chunk 加载失败', () => {
  it('不抛错（遥测失败不得影响业务）', async () => {
    markSentryReady(true)

    expect(() => reportError(new Error('boom'))).not.toThrow()
    await tick()
    // reportError 内部已 catch；此处只需确认没有未处理的拒绝冒出来
    expect(attempts.count).toBeGreaterThanOrEqual(1)
  })

  it('失败不被缓存：后续上报仍会重新尝试加载', async () => {
    markSentryReady(true)
    const before = attempts.count

    reportError(new Error('retry-1'))
    await tick()
    const afterFirst = attempts.count

    reportError(new Error('retry-2'))
    await tick()
    const afterSecond = attempts.count

    expect(afterFirst).toBeGreaterThan(before)
    expect(afterSecond).toBeGreaterThan(afterFirst)
  })
})
