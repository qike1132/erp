import { beforeEach, describe, expect, it, vi } from 'vitest'
import { notificationApi, type NotificationListResponse } from '@/api/notification'
import {
  clearNotificationMemoryCache,
  fetchNotificationList,
  getNotificationMemorySnapshot,
} from '@/composables/notificationMemoryCache'

vi.mock('@/api/notification', () => ({
  notificationApi: {
    list: vi.fn(),
  },
}))

const baseParams = { page: 1, page_size: 20, only_unread: true }

function makeResponse(title: string): NotificationListResponse {
  return {
    total: 1,
    page: 1,
    page_size: 20,
    data: [{
      id: 1,
      user_id: 7,
      type: 'new_order',
      title,
      content: null,
      related_order_id: null,
      is_read: false,
      created_at: null,
    }],
  }
}

describe('notificationMemoryCache', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearNotificationMemoryCache()
  })

  it('缓存新鲜快照并隔离返回对象，避免调用方修改共享缓存', async () => {
    vi.mocked(notificationApi.list).mockResolvedValue(makeResponse('原始通知'))

    const response = await fetchNotificationList(baseParams)
    response.data[0]!.title = '调用方修改'

    const snapshot = getNotificationMemorySnapshot(baseParams)
    expect(snapshot?.fresh).toBe(true)
    expect(snapshot?.response.data[0]?.title).toBe('原始通知')
    expect(notificationApi.list).toHaveBeenCalledTimes(1)
  })

  it('超过 TTL 后保留旧快照但标记为过期，供后台静默刷新使用', async () => {
    vi.useFakeTimers()
    try {
      vi.setSystemTime(new Date('2026-08-20T00:00:00Z'))
      vi.mocked(notificationApi.list).mockResolvedValue(makeResponse('旧通知'))
      await fetchNotificationList(baseParams)

      vi.advanceTimersByTime(5_001)
      const snapshot = getNotificationMemorySnapshot(baseParams)
      expect(snapshot?.fresh).toBe(false)
      expect(snapshot?.response.data[0]?.title).toBe('旧通知')
    } finally {
      vi.useRealTimers()
    }
  })

  it('清理缓存后，旧账号的 in-flight 响应不能污染下一次会话', async () => {
    let resolveOld!: (response: NotificationListResponse) => void
    vi.mocked(notificationApi.list)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
      .mockResolvedValueOnce(makeResponse('新账号通知'))

    const oldRequest = fetchNotificationList(baseParams)
    clearNotificationMemoryCache()
    const newRequest = fetchNotificationList(baseParams)

    resolveOld(makeResponse('旧账号通知'))
    await oldRequest
    await newRequest

    const snapshot = getNotificationMemorySnapshot(baseParams)
    expect(snapshot?.response.data[0]?.title).toBe('新账号通知')
    expect(notificationApi.list).toHaveBeenCalledTimes(2)
  })
})
