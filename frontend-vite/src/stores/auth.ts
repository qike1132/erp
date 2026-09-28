import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, dashboardApi, clearCsrfCache } from '@/api'
import type { User, UserInfo, NavSection } from '@/types'
import { useCatalogStore } from './catalog'
import { usePatternRoomStore } from './patternRoom'
import { queryClient, queryPersister } from '@/utils/queryClient'
import { clearNotificationMemoryCache } from '@/composables/notificationMemoryCache'
import { purgeApiCaches } from '@/utils/swCache'

/**
 * 用户信息会话快照：登录成功后写入 sessionStorage（仅当前标签页，关闭即失效），
 * 页面刷新（F5）后 init() 先命中快照、跳过阻塞导航的 /auth/me 请求，
 * 再后台静默刷新校验权限；登出时清除，不影响安全。
 */
const USER_SNAPSHOT_KEY = 'fb_auth_user_snapshot_v1'

function readUserSnapshot(): User | null {
  try {
    const raw = sessionStorage.getItem(USER_SNAPSHOT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<User> | null
    if (!parsed || typeof parsed !== 'object') return null
    // 完整性校验：字段不完整视为无效快照（与 setUserInfo 的产出结构一致）
    if (typeof parsed.username !== 'string' || typeof parsed.id !== 'number') return null
    return parsed as User
  } catch {
    return null
  }
}

function writeUserSnapshot(user: User | null | undefined): void {
  try {
    if (!user) {
      sessionStorage.removeItem(USER_SNAPSHOT_KEY)
      return
    }
    sessionStorage.setItem(USER_SNAPSHOT_KEY, JSON.stringify(user))
  } catch {
    // 隐私模式 / 容量不足时静默降级（不影响主流程）
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const navSections = ref<NavSection[]>([])
  const loaded = ref(false)
  let _initPromise: Promise<void> | null = null
  // 防止登出/切换账号后，旧的用户信息或导航请求回写当前 store。
  let authGeneration = 0

  const isLoggedIn = computed(() => !!user.value)
  const permissionSet = computed(() => new Set(user.value?.permissions ?? []))

  function clearUserCaches(): void {
    // 清空目录缓存（产品/客户/供应商下拉数据），避免跨账号残留
    useCatalogStore().clear()
    // 清空打样间数据缓存，避免跨账号残留
    usePatternRoomStore().clear()
    // 通知只使用 JS 内存 SWR，登出时显式清空，避免跨账号复用
    clearNotificationMemoryCache()
    // 清空 Vue Query 缓存及其 sessionStorage 持久化，避免跨账号数据串用
    queryClient.clear()
    if (queryPersister) {
      // removeClient() 返回 Promisable<void>，用 Promise.resolve 统一包装吞掉失败
      void Promise.resolve(queryPersister.removeClient()).catch(() => { /* 静默 */ })
    }
  }

  /** 将 API 返回的用户信息映射为内部 User 类型（兼容已归一化的内部 User 快照） */
  function setUserInfo(raw: UserInfo | User | null | undefined) {
    if (!raw || typeof raw !== 'object') {
      console.error('[Auth] setUserInfo 收到无效数据:', raw)
      return null
    }
    const rawUser = raw as UserInfo | { id?: number; user_id?: number; username?: string; is_super?: boolean; factory?: string | null; permissions?: string[] }
    const id = rawUser.user_id ?? (rawUser as { id?: number }).id ?? 0
    const username = rawUser.username || ''
    // 身份有效性校验（防"伪用户"）：
    // 合法的登录用户必定同时具备正整数 id 与非空用户名。
    // 若响应形状异常（例如被错误地传入了外层包装对象 { user: null }），
    // 会映射出 { id: 0, username: '' } —— 这种"伪用户"会让 user.value 变为
    // truthy，使前端呈现"已登录空壳态"（用户名为空、全站无权限入口），
    // 且不会触发 401 登出流程。此处直接拒绝，交由调用方的 401 路径处理。
    if (!id || !username) {
      console.error('[Auth] setUserInfo 收到无效身份（缺少 id 或 username）:', raw)
      return null
    }
    const nextUser: User = {
      id,
      username,
      is_super: rawUser.is_super ?? false,
      factory: rawUser.factory ?? null,
      permissions: Array.isArray(rawUser.permissions) ? rawUser.permissions : [],
    }
    // 同一标签页切换账号时，先清掉旧账号的内存和持久化查询。
    if (user.value && user.value.id !== nextUser.id) clearUserCaches()
    authGeneration += 1
    user.value = nextUser
    return nextUser
  }

  async function fetchUser() {
    const requestGeneration = authGeneration
    const res = await authApi.me()
    // 请求可能在 logout() 或另一账号登录后才完成，不能再写回旧响应。
    if (requestGeneration !== authGeneration) return null
    // 后端 /auth/me 返回扁平 UserInfo（用户无效时直接 401，不会返回 { user: null }）。
    // 这里兼容仍可能返回 { user } 包装层的部署形态，但**显式判 undefined**：
    // 不能用 `res.user ?? res` —— 当 user 为 null 时 `null ?? res` 会退化成外层
    // 包装对象，进而被 setUserInfo 误判为合法用户。
    const payload = res && typeof res === 'object' && 'user' in res
      ? (res as { user?: UserInfo | null }).user
      : res
    return setUserInfo(payload)
  }

  type NavApiItem = { name: string; url: string; icon?: string; code: string; permission_codes: string[] }
  type NavApiSection = { name?: string; items?: NavApiItem[] }

  // 导航数据在途 Promise：init() 后台触发、路由守卫 await 同一 Promise，
  // 避免 fail-closed 权限检查在导航数据就绪前竞态取消导航（登录后永久卡"登录中"）。
  let _navPromise: Promise<void> | null = null

  async function fetchNavSections() {
    const requestGeneration = authGeneration
    const res = await dashboardApi.navSections()
    if (requestGeneration !== authGeneration) return
    if (Array.isArray(res)) {
      navSections.value = res
    } else if (res && typeof res === 'object') {
      navSections.value = Object.entries(res)
        .filter(([_key, val]) => val && typeof val === 'object' && !Array.isArray(val))
        .map(([_key, val]: [string, NavApiSection]) => ({
        key: _key,
        title: val.name ?? _key,
        items: (val.items ?? []).map((item: NavApiItem) => ({
          title: item.name,
          path: item.url,
          icon: item.icon,
          permission: item.code,
          permissionCodes: item.permission_codes ?? [item.code],
        })),
      }))
    }
  }

  /** 触发/复用导航数据加载 Promise；成功 resolve 时 navSections 已填充 */
  function loadNavSections(): Promise<void> {
    if (!_navPromise) {
      _navPromise = fetchNavSections().finally(() => {
        _navPromise = null
      })
    }
    return _navPromise
  }

  async function init(force = false) {
    if (loaded.value && !force) return
    // 防止并发调用：多个导航同时触发时复用同一个 Promise
    if (_initPromise && !force) return _initPromise

    _initPromise = (async () => {
      try {
        if (!user.value) {
          // 优先命中会话快照：跳过阻塞导航的 /auth/me，立即放行路由
          const snapshot = force ? null : readUserSnapshot()
          if (snapshot) {
            setUserInfo(snapshot)
            // 静默刷新用户信息（校验会话有效性/权限变更）：
            // 必须 await 结算后再拉取导航，否则 setUserInfo 递增 authGeneration，
            // 会把并发 fetchNavSections 的响应误判为过期而丢弃 → 侧边栏偶发空白。
            // 失败（如 401）由 request 拦截器的 auth:expired 统一登出处理
            await fetchUser()
              .then((u) => writeUserSnapshot(u))
              .catch(() => {
                /* 静默：路线转移给 auth:expired 事件 */
              })
          } else {
            await fetchUser()
          }
        }
        // 登出可能发生在 /auth/me 请求期间；此时不要把未登录状态标记为已加载。
        if (!user.value) {
          loaded.value = false
          return
        }
        // 用户信息就绪：统一写入会话快照（覆盖快照命中、接口拉取、登录预置三种路径），
        // 页面刷新后首次导航可直接命中，跳过 /auth/me 阻塞
        writeUserSnapshot(user.value)
        // 用户信息就绪后立即标记 loaded，导航可提前进行
        // nav-sections 非关键路径，后台加载不阻塞路由跳转
        loaded.value = true

        loadNavSections().catch((e) => {
          console.error('[Auth] 导航数据加载失败:', e)
        })
      } catch (error) {
        loaded.value = false
        throw error
      } finally {
        _initPromise = null
      }
    })()

    return _initPromise
  }

  function hasPermission(code: string): boolean {
    if (user.value?.is_super) return true
    return user.value?.permissions?.includes(code) ?? false
  }

  function hasAnyPermission(codes: string[]): boolean {
    if (user.value?.is_super) return true
    return codes.some((code) => permissionSet.value.has(code))
  }

  const filteredNavSections = computed(() => {
    return navSections.value
      .map((section) => ({
        ...section,
        items: section.items.filter((item) => {
          const codes = item.permissionCodes ?? (item.permission ? [item.permission] : [])
          return codes.length === 0 || hasAnyPermission(codes)
        }),
      }))
      .filter((section) => section.items.length > 0)
  })

  function logout() {
    authGeneration += 1
    user.value = null
    navSections.value = []
    loaded.value = false
    clearCsrfCache()
    try {
      sessionStorage.removeItem(USER_SNAPSHOT_KEY)
    } catch { /* 静默 */ }
    clearUserCaches()
    // 纵深防御：清掉 Service Worker 的 api-* 运行时缓存（残留旧 SW 或将来再启用
    // API 缓存时，防止共用终端上后一位用户读到前一位用户的响应）。不阻塞登出。
    void purgeApiCaches()
  }

  return { user, navSections, filteredNavSections, loaded, isLoggedIn, setUserInfo, init, fetchUser, fetchNavSections, loadNavSections, hasPermission, hasAnyPermission, logout }
})
