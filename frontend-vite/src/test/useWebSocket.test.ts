import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { websocketApi } from '@/api/auth'
import { useWebSocket } from '@/composables/useWebSocket'

type MockSocket = {
  onopen: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  readyState: number
}

type WebSocketMock = ReturnType<typeof vi.fn> & { OPEN: number }

function createMockSocket(): MockSocket {
  const socket: MockSocket = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send: vi.fn(),
    close: vi.fn(),
    readyState: 1,
  }
  const WebSocketMock = vi.fn(function () { return socket }) as WebSocketMock
  WebSocketMock.OPEN = 1
  vi.stubGlobal('WebSocket', WebSocketMock)
  return socket
}

type WebSocketMessage = { type: string; [key: string]: unknown }

function mountWebSocket(onMessage: (data: WebSocketMessage) => void) {
  let cleanup: (() => void) | undefined

  const wrapper = mount(
    defineComponent({
      setup() {
        cleanup = useWebSocket({ onMessage, isActive: ref(true) }).cleanup
        return () => h('div')
      },
    }),
  )

  return {
    cleanup: () => cleanup?.(),
    unmount: () => wrapper.unmount(),
  }
}

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(websocketApi, 'ticket').mockResolvedValue({ ticket: 'ws-ticket' })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('连接建立后启动心跳', async () => {
    const socket = createMockSocket()
    const { cleanup, unmount } = mountWebSocket(vi.fn<(data: WebSocketMessage) => void>())

    await vi.waitFor(() => expect(socket.onopen).not.toBeNull())
    socket.onopen?.()
    expect(socket.send).toHaveBeenNthCalledWith(
      1,
      JSON.stringify({ type: 'auth', token: 'ws-ticket' }),
    )

    vi.advanceTimersByTime(30_000)
    expect(socket.send).toHaveBeenCalledWith('ping')

    cleanup()
    unmount()
  })

  it('清理时停止心跳', async () => {
    const socket = createMockSocket()
    const { cleanup, unmount } = mountWebSocket(vi.fn<(data: WebSocketMessage) => void>())

    await vi.waitFor(() => expect(socket.onopen).not.toBeNull())
    socket.onopen?.()
    cleanup()
    const sendCount = socket.send.mock.calls.length
    vi.advanceTimersByTime(60_000)
    expect(socket.send.mock.calls.length).toBe(sendCount)

    unmount()
  })
})
