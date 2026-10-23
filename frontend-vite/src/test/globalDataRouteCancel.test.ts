/**
 * P1-09 / P1-10 回归：跨路由存活的数据必须声明 routeCancel:false。
 *
 * 通知中心与打样间详情由 keep-alive/跨路由缓存持有；走默认路由取消时，
 * 切路由 abort 后 request.ts 的 _silenceCanceled 让 Promise 永不 settle，
 * loading/finally 永不执行，用户回来看到永久「加载中」。
 */
import { describe, it, expect, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  get: vi.fn((
    _url: string,
    _params?: Record<string, unknown>,
    _options?: { routeCancel?: boolean },
  ) => Promise.resolve({})),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.get,
  post: mocks.post,
  put: mocks.put,
  del: mocks.del,
  upload: mocks.upload,
}))

import { notificationApi } from '@/api/notification'
import { patternRoomApi } from '@/api/patternRoom'

describe('全局数据不走路由取消', () => {
  it('通知未读数与列表固定 routeCancel:false', () => {
    notificationApi.unreadCount()
    expect(mocks.get).toHaveBeenLastCalledWith(
      '/notifications/unread-count', undefined, { routeCancel: false },
    )
    notificationApi.list({ page: 1 })
    expect(mocks.get).toHaveBeenLastCalledWith(
      '/notifications', { page: 1 }, { routeCancel: false },
    )
  })

  it('打样间详情读固定 routeCancel:false', () => {
    patternRoomApi.getProject(1)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.listParts(1)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.listVersions(1)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.getVersionDetail(2)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.getPartsByVersion(1)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.listRoles(1)
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
    patternRoomApi.getPartFieldCandidates()
    expect(mocks.get.mock.lastCall?.[2]).toEqual({ routeCancel: false })
  })
})
