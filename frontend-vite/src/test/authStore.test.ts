import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// ---------------------------------------------------------------------------
// 模块级 mock：auth store 在导入时就绑定了这些依赖
//
// 注意：vi.mock 的工厂函数会被提升到文件顶部执行，因此工厂内**不能**直接引用
// 下方用 const 声明的变量（会报 "Cannot access 'x' before initialization"）。
// 必须用 vi.hoisted() 把 mock 对象一起提升。
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  authApi: { me: vi.fn(), login: vi.fn(), logout: vi.fn() },
  dashboardApi: { navSections: vi.fn() },
  clearCsrfCache: vi.fn(),
  clearCatalog: vi.fn(),
  clearPatternRoom: vi.fn(),
  clearNotificationCache: vi.fn(),
  queryClientClear: vi.fn(),
  removeClient: vi.fn(() => Promise.resolve()),
}))

vi.mock('@/api', () => ({
  authApi: mocks.authApi,
  dashboardApi: mocks.dashboardApi,
  clearCsrfCache: mocks.clearCsrfCache,
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({ clear: mocks.clearCatalog }),
}))
vi.mock('@/stores/patternRoom', () => ({
  usePatternRoomStore: () => ({ clear: mocks.clearPatternRoom }),
}))
vi.mock('@/composables/notificationMemoryCache', () => ({
  clearNotificationMemoryCache: mocks.clearNotificationCache,
}))
vi.mock('@/utils/queryClient', () => ({
  queryClient: { clear: mocks.queryClientClear },
  queryPersister: { removeClient: mocks.removeClient },
}))

const mockAuthApi = mocks.authApi
const mockDashboardApi = mocks.dashboardApi
const mockClearCsrfCache = mocks.clearCsrfCache
const mockClearCatalog = mocks.clearCatalog
const mockClearPatternRoom = mocks.clearPatternRoom
const mockClearNotificationCache = mocks.clearNotificationCache
const mockQueryClientClear = mocks.queryClientClear

// ---------------------------------------------------------------------------

import { useAuthStore } from '@/stores/auth'

const SNAPSHOT_KEY = 'fb_auth_user_snapshot_v1'

/** 使用 store 前必须 setActivePinia（组合式 store 依赖注入的 pinia 实例） */
function freshStore() {
  setActivePinia(createPinia())
  return useAuthStore()
}

const superUser = {
  id: 1,
  username: 'admin',
  is_super: true,
  factory: null,
  permissions: [],
}

const normalUser = {
  id: 2,
  username: 'zhangsan',
  is_super: false,
  factory: 'F1',
  permissions: ['order:view', 'order:edit'],
}

describe('auth store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    mockAuthApi.me.mockResolvedValue({ user: superUser })
    mockDashboardApi.navSections.mockResolvedValue([])
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  describe('setUserInfo', () => {
    it('映射 user_id 字段为内部 id', () => {
      const s = freshStore()
      s.setUserInfo({ user_id: 7, username: 'u7', is_super: false, factory: null, permissions: [] })
      expect(s.user?.id).toBe(7)
    })

    it('兼容已归一化的内部 User 快照（用 id 而非 user_id）', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      expect(s.user?.id).toBe(2)
      expect(s.user?.username).toBe('zhangsan')
    })

    it('is_super 缺失时默认 false（不误授管理权限）', () => {
      const s = freshStore()
      s.setUserInfo({ user_id: 9, username: 'u9' } as never)
      expect(s.user?.is_super).toBe(false)
    })

    it('permissions 非数组时降级为空数组（不抛异常）', () => {
      const s = freshStore()
      s.setUserInfo({ user_id: 9, username: 'u9', permissions: 'not-an-array' } as never)
      expect(s.user?.permissions).toEqual([])
    })

    it('无效输入返回 null 且不写入 user', () => {
      const s = freshStore()
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
      expect(s.setUserInfo(null)).toBeNull()
      expect(s.setUserInfo(undefined)).toBeNull()
      expect(s.setUserInfo('str' as never)).toBeNull()
      expect(s.user).toBeNull()
      spy.mockRestore()
    })

    it('切换账号（id 变化）时清理跨账号缓存', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      vi.clearAllMocks()
      s.setUserInfo(superUser) // id 2 → 1，属切换账号
      expect(mockClearCatalog).toHaveBeenCalled()
      expect(mockClearPatternRoom).toHaveBeenCalled()
      expect(mockClearNotificationCache).toHaveBeenCalled()
      expect(mockQueryClientClear).toHaveBeenCalled()
    })

    it('同一账号刷新（id 相同）不清理缓存（避免无谓清空）', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      vi.clearAllMocks()
      s.setUserInfo({ ...normalUser, username: 'zhangsan-renamed' })
      expect(mockClearCatalog).not.toHaveBeenCalled()
      expect(mockQueryClientClear).not.toHaveBeenCalled()
    })
  })

  describe('权限判定', () => {
    it('isLoggedIn 随 user 变化', () => {
      const s = freshStore()
      expect(s.isLoggedIn).toBe(false)
      s.setUserInfo(normalUser)
      expect(s.isLoggedIn).toBe(true)
    })

    it('hasPermission：超管恒为 true（无需显式授权）', () => {
      const s = freshStore()
      s.setUserInfo(superUser)
      expect(s.hasPermission('anything')).toBe(true)
    })

    it('hasPermission：普通用户按 permissions 精确匹配', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      expect(s.hasPermission('order:view')).toBe(true)
      expect(s.hasPermission('order:delete')).toBe(false)
    })

    it('hasPermission：未登录返回 false', () => {
      const s = freshStore()
      expect(s.hasPermission('order:view')).toBe(false)
    })

    it('hasAnyPermission：任一命中即为 true', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      expect(s.hasAnyPermission(['nope', 'order:edit'])).toBe(true)
      expect(s.hasAnyPermission(['nope', 'other'])).toBe(false)
    })

    it('hasAnyPermission：空数组为 false（不误放行）', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      expect(s.hasAnyPermission([])).toBe(false)
    })
  })

  describe('filteredNavSections', () => {
    it('按权限过滤导航项，并剔除空分组', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      s.navSections = [
        {
          key: 'a',
          title: 'A',
          items: [
            { title: '可见', path: '/v', permissionCodes: ['order:view'] },
            { title: '不可见', path: '/x', permissionCodes: ['admin:all'] },
          ],
        },
        {
          key: 'b',
          title: 'B',
          items: [{ title: '全不可见', path: '/y', permissionCodes: ['admin:all'] }],
        },
      ] as never

      const result = s.filteredNavSections
      expect(result).toHaveLength(1)
      expect(result[0]!.key).toBe('a')
      expect(result[0]!.items.map((i) => i.title)).toEqual(['可见'])
    })

    it('无权限声明的导航项对所有登录用户可见', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      s.navSections = [
        { key: 'a', title: 'A', items: [{ title: '公开项', path: '/pub' }] },
      ] as never
      expect(s.filteredNavSections[0]!.items).toHaveLength(1)
    })

    it('回退到单项 permission 字段（无 permissionCodes 时）', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      s.navSections = [
        { key: 'a', title: 'A', items: [{ title: 'T', path: '/t', permission: 'order:view' }] },
      ] as never
      expect(s.filteredNavSections[0]!.items).toHaveLength(1)
    })

    it('超管看到全部导航项', () => {
      const s = freshStore()
      s.setUserInfo(superUser)
      s.navSections = [
        {
          key: 'a',
          title: 'A',
          items: [
            { title: 'x', path: '/x', permissionCodes: ['admin:all'] },
            { title: 'y', path: '/y', permissionCodes: ['other'] },
          ],
        },
      ] as never
      expect(s.filteredNavSections[0]!.items).toHaveLength(2)
    })
  })

  describe('fetchUser 竞态保护', () => {
    it('logout 后到达的 /auth/me 响应被丢弃（不复活已登出会话）', async () => {
      const s = freshStore()
      let resolveMe: (v: unknown) => void = () => {}
      mockAuthApi.me.mockReturnValue(new Promise((r) => { resolveMe = r }))

      const pending = s.fetchUser()
      s.logout() // 递增 authGeneration
      resolveMe({ user: superUser })

      await expect(pending).resolves.toBeNull()
      expect(s.user).toBeNull()
    })

    it('正常路径写入用户信息', async () => {
      const s = freshStore()
      mockAuthApi.me.mockResolvedValue({ user: normalUser })
      await s.fetchUser()
      expect(s.user?.username).toBe('zhangsan')
    })

    it('响应无 user 字段时回退使用顶层对象', async () => {
      const s = freshStore()
      mockAuthApi.me.mockResolvedValue(normalUser)
      await s.fetchUser()
      expect(s.user?.id).toBe(2)
    })
  })

  describe('init', () => {
    it('已有 user 时不再请求 /auth/me', async () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      vi.clearAllMocks()
      await s.init()
      expect(mockAuthApi.me).not.toHaveBeenCalled()
    })

    it('无快照时拉取用户信息并标记 loaded', async () => {
      const s = freshStore()
      await s.init()
      expect(s.user?.username).toBe('admin')
      expect(s.loaded).toBe(true)
    })

    it('并发调用只发一次请求（去重）', async () => {
      const s = freshStore()
      const p1 = s.init()
      const p2 = s.init()
      // 注意：init 是 async 函数，即使内部 return 同一个 _initPromise，
      // async 包装也会产生**新的** Promise 对象，故 p1 !== p2 是语言语义使然。
      // 真正的契约是"不重复发起请求"，因此断言调用次数而非 Promise 同一性。
      await Promise.all([p1, p2])
      expect(mockAuthApi.me).toHaveBeenCalledTimes(1)
    })

    it('force=true 重跑 init，但已有 user 时不再拉取 /auth/me', async () => {
      const s = freshStore()
      await s.init()
      expect(s.loaded).toBe(true)
      vi.clearAllMocks()
      await s.init(true)
      // user 已存在 → 跳过 `if (!user.value)` 分支，不会重复请求用户信息
      expect(mockAuthApi.me).not.toHaveBeenCalled()
    })

    it('命中 sessionStorage 快照时先置用户，避免阻塞路由', async () => {
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(normalUser))
      const s = freshStore()
      await s.init()
      expect(s.loaded).toBe(true)
      // 快照命中后仍会静默刷新校验权限
      expect(mockAuthApi.me).toHaveBeenCalled()
    })

    it('快照损坏（JSON 非法）时降级为走接口', async () => {
      sessionStorage.setItem(SNAPSHOT_KEY, '{not json')
      const s = freshStore()
      await s.init()
      expect(s.user?.username).toBe('admin')
    })

    it('快照字段不完整（缺 id）视为无效', async () => {
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify({ username: 'onlyname' }))
      const s = freshStore()
      await s.init()
      // 未采用无效快照，仍以接口结果为准
      expect(s.user?.id).toBe(1)
    })

    it('/auth/me 失败时不标记 loaded 并向上抛错', async () => {
      mockAuthApi.me.mockRejectedValue(new Error('401'))
      const s = freshStore()
      await expect(s.init()).rejects.toThrow('401')
      expect(s.loaded).toBe(false)
    })

    it('导航请求失败不影响 loaded（非关键路径）', async () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
      mockDashboardApi.navSections.mockRejectedValue(new Error('nav down'))
      const s = freshStore()
      await s.init()
      expect(s.loaded).toBe(true)
      spy.mockRestore()
    })

    it('{user:null} 不得造出伪用户（原缺陷回归防护）', async () => {
      // 缺陷复现：原实现 fetchUser 用 `res.user ?? res`。
      // 当 user 为 null 时，`null ?? res` 得到**外层对象** {user: null}，
      // 它能通过 setUserInfo 的 typeof === 'object' 校验，生成
      // {id:0, username:'', is_super:false, permissions:[]} 并写入 user，
      // 使 user.value 变为 truthy → loaded=true → 呈"已登录空壳态"。
      //
      // 修复后：fetchUser 显式判 undefined 取 user 字段，
      // setUserInfo 进一步校验 id/username 必填，双重兜底。
      mockAuthApi.me.mockResolvedValue({ user: null })
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const s = freshStore()
      await s.init()

      expect(s.user).toBeNull()
      expect(s.isLoggedIn).toBe(false)
      expect(s.loaded).toBe(false)
      errSpy.mockRestore()
    })

    it('setUserInfo 拒绝缺少 id 或 username 的身份（伪用户第二道防线）', () => {
      const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const s = freshStore()

      expect(s.setUserInfo({ username: 'no-id' } as never)).toBeNull()
      expect(s.setUserInfo({ id: 5 } as never)).toBeNull()
      expect(s.setUserInfo({ id: 0, username: 'zero-id' } as never)).toBeNull()
      expect(s.setUserInfo({ id: 5, username: '' } as never)).toBeNull()
      expect(s.user).toBeNull()
      errSpy.mockRestore()
    })

    it('兼容仍返回 { user: {...} } 包装层的部署形态', async () => {
      mockAuthApi.me.mockResolvedValue({ user: normalUser })
      const s = freshStore()
      await s.fetchUser()
      expect(s.user?.id).toBe(2)
      expect(s.user?.username).toBe('zhangsan')
    })
  })

  describe('fetchNavSections', () => {
    it('数组响应直接赋值', async () => {
      const s = freshStore()
      mockDashboardApi.navSections.mockResolvedValue([
        { key: 'k', title: 'T', items: [] },
      ])
      await s.fetchNavSections()
      expect(s.navSections).toHaveLength(1)
    })

    it('对象响应按 name/items 映射为分组结构', async () => {
      const s = freshStore()
      mockDashboardApi.navSections.mockResolvedValue({
        product: {
          name: '产品',
          items: [
            { name: '产品列表', url: '/products', icon: 'pi-box', code: 'product:view', permission_codes: ['product:view'] },
          ],
        },
      })
      await s.fetchNavSections()
      expect(s.navSections[0]!.key).toBe('product')
      expect(s.navSections[0]!.title).toBe('产品')
      expect(s.navSections[0]!.items[0]!.path).toBe('/products')
      expect(s.navSections[0]!.items[0]!.permissionCodes).toEqual(['product:view'])
    })

    it('对象响应缺少 name 时回退用 key 作标题', async () => {
      const s = freshStore()
      mockDashboardApi.navSections.mockResolvedValue({ misc: { items: [] } })
      await s.fetchNavSections()
      expect(s.navSections[0]!.title).toBe('misc')
    })

    it('permission_codes 缺失时回退为 [code]', async () => {
      const s = freshStore()
      mockDashboardApi.navSections.mockResolvedValue({
        g: { name: 'G', items: [{ name: 'I', url: '/i', code: 'c1' }] },
      })
      await s.fetchNavSections()
      expect(s.navSections[0]!.items[0]!.permissionCodes).toEqual(['c1'])
    })

    it('登出后到达的导航响应被丢弃', async () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      let resolveNav: (v: unknown) => void = () => {}
      mockDashboardApi.navSections.mockReturnValue(new Promise((r) => { resolveNav = r }))

      const pending = s.fetchNavSections()
      s.logout()
      resolveNav([{ key: 'stale', title: 'S', items: [] }])
      await pending

      expect(s.navSections).toEqual([])
    })
  })

  describe('logout', () => {
    it('清空用户、导航与 loaded 状态', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      s.loaded = true
      s.navSections = [{ key: 'k', title: 'T', items: [] }] as never

      s.logout()

      expect(s.user).toBeNull()
      expect(s.navSections).toEqual([])
      expect(s.loaded).toBe(false)
      expect(s.isLoggedIn).toBe(false)
    })

    it('清理 CSRF 缓存、会话快照与跨账号缓存', () => {
      const s = freshStore()
      s.setUserInfo(normalUser)
      sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(normalUser))
      vi.clearAllMocks()

      s.logout()

      expect(mockClearCsrfCache).toHaveBeenCalled()
      expect(sessionStorage.getItem(SNAPSHOT_KEY)).toBeNull()
      expect(mockClearCatalog).toHaveBeenCalled()
      expect(mockQueryClientClear).toHaveBeenCalled()
    })
  })
})
