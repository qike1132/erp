/**
 * M9 回归锁：ticket Promise 不得把 WebSocket 连接状态永久钉住。
 *
 * 背景（2026-10-26 上线前检查 M9）
 * -------------------------------
 * `abortPendingRequests()`（路由守卫）取消在途请求时，`_silenceCanceled()` 返回的是
 * **永不 settle** 的 Promise（不是 reject）。ticket 请求原先走默认 tracked——
 * 一旦在导航时被取消，`connect()` 的 `await` 永久挂起，`connecting` 停在 true
 *（`finally` 也不执行），该实例再也不会重连。
 *
 * 两层修复各自锁一条：
 * 1. ticket 请求 `routeCancel:false`（静态断言）；
 * 2. `connect()` 对 ticket 加硬超时，任何永不 settle 的 Promise 都不能卡死连接。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const ticket = vi.fn()

vi.mock('@/api/auth', () => ({ websocketApi: { ticket: () => ticket() } }))

import { useWebSocket } from '@/composables/useWebSocket'

describe('useWebSocket ticket 生命周期（M9）', () => {
  beforeEach(() => {
    ticket.mockReset()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('ticket 请求必须 routeCancel:false（不被路由守卫取消）', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/api/auth.ts'), 'utf-8',
    )
    const line = source.split('\n').find((l) => l.includes('/notifications/ws-ticket'))
    expect(line).toBeTruthy()
    expect(source).toMatch(
      /ticket:\s*\(\)\s*=>\s*get<[^>]*>\(\s*['"]\/notifications\/ws-ticket['"][^)]*routeCancel:\s*false/s,
    )
    expect(source).toContain('M9')
  })

  it('ticket 永不 settle 时连接状态必须能恢复（超时后重试）', async () => {
    const wsCtor = vi.fn()
    vi.stubGlobal('WebSocket', wsCtor)
    ticket.mockReturnValue(new Promise(() => {}))  // 永不 settle

    mount(defineComponent({
      setup() {
        useWebSocket({ onMessage: vi.fn(), isActive: ref(true) })
        return () => h('div')
      },
    }))

    await Promise.resolve()
    expect(ticket).toHaveBeenCalledTimes(1)
    expect(wsCtor).not.toHaveBeenCalled()

    // 超时上限（10s）到点后必须释放 connecting 并安排重试
    await vi.advanceTimersByTimeAsync(10_000)
    await vi.advanceTimersByTimeAsync(3_000)

    expect(ticket.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('ticket 正常返回时照常建立连接（防过度收敛）', async () => {
    const sockets: { readyState: number; send: () => void; close: () => void }[] = []
    class FakeWS {
      readyState = 0
      onopen: (() => void) | null = null
      onmessage: (() => void) | null = null
      onclose: (() => void) | null = null
      onerror: (() => void) | null = null
      sent: string[] = []
      constructor() { sockets.push(this as unknown as never) }
      send(msg: string) { this.sent.push(msg) }
      close() { this.readyState = 3 }
    }
    vi.stubGlobal('WebSocket', FakeWS)
    vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:3000' } })
    ticket.mockResolvedValue({ ticket: 't-1' })

    mount(defineComponent({
      setup() {
        useWebSocket({ onMessage: vi.fn(), isActive: ref(true) })
        return () => h('div')
      },
    }))
    await vi.advanceTimersByTimeAsync(0)

    expect(sockets).toHaveLength(1)
  })
})
