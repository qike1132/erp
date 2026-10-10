import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * patternRoomStore.prefetch 的权限门控测试。
 *
 * 背景（用户报「其他用户登录进去显示无权限」）：登录成功后 useLogin 无条件调用
 * patternRoomStore().prefetch()。该函数起初只给「版师列表」预取加了
 * customer_sampling_manage 门控，却漏了「分组列表」——于是任何没有板房权限的用户
 * 一登录都会发一次注定 403 的 /pattern-room/grouped-list，触发全局 axios 拦截器
 * 弹「权限不足」。期望：无读权限 → 一个请求都不发。
 */
const mocks = vi.hoisted(() => ({
  getGroupedListMock: vi.fn(),
  listMakersMock: vi.fn(),
  hasAnyPermissionMock: vi.fn(),
  hasPermissionMock: vi.fn(),
}))

vi.mock('@/api/patternRoom', () => ({
  patternRoomApi: { getGroupedList: mocks.getGroupedListMock },
}))

vi.mock('@/api/patternMaker', () => ({
  patternMakerApi: { list: mocks.listMakersMock },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasAnyPermission: mocks.hasAnyPermissionMock,
    hasPermission: mocks.hasPermissionMock,
  }),
}))

import { usePatternRoomStore } from '@/stores/patternRoom'

const emptyGrouped = {
  success: true, groups: [], total_projects: 0, total: 0,
  pages: 1, current_page: 1,
}

describe('patternRoomStore.prefetch 权限门控', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.clearAllMocks()
    mocks.getGroupedListMock.mockResolvedValue(emptyGrouped)
    mocks.listMakersMock.mockResolvedValue({ items: [] })
  })

  it('无板房权限：分组列表与版师列表都不预取（不产生 403 噪音）', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(false)
    mocks.hasPermissionMock.mockReturnValue(false)

    await usePatternRoomStore().prefetch()

    expect(mocks.getGroupedListMock).not.toHaveBeenCalled()
    expect(mocks.listMakersMock).not.toHaveBeenCalled()
  })

  it('有 customer_sampling_manage：预取分组列表 + 版师列表', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    mocks.hasPermissionMock.mockReturnValue(true)

    await usePatternRoomStore().prefetch()

    expect(mocks.getGroupedListMock).toHaveBeenCalledTimes(1)
    expect(mocks.listMakersMock).toHaveBeenCalledTimes(1)
  })

  it('只有读权限（view）、无 manage：预取分组列表，但不预取版师列表', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    mocks.hasPermissionMock.mockReturnValue(false)

    await usePatternRoomStore().prefetch()

    expect(mocks.getGroupedListMock).toHaveBeenCalledTimes(1)
    expect(mocks.listMakersMock).not.toHaveBeenCalled()
  })
})
