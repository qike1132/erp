import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, dashboardApi } from '@/api'
import type { User, NavSection } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const navSections = ref<NavSection[]>([])
  const loaded = ref(false)

  const isLoggedIn = computed(() => !!user.value)

  async function fetchUser() {
    const res: any = await authApi.me()
    // 后端返回 {user_id, username, is_super, permissions}，需要映射
    const raw = res.user ?? res
    user.value = {
      id: raw.user_id ?? raw.id,
      username: raw.username,
      isSuper: raw.is_super ?? raw.isSuper ?? false,
      permissions: raw.permissions ?? [],
    }
    return user.value
  }

  async function fetchNavSections() {
    const res: any = await dashboardApi.navSections()
    // 后端返回 {purchase: {name, items}, core: {name, items}, ...}
    // 每个 item: {id, name, code, icon, url, permission_codes}
    // 需要转为 NavSection[] 并映射字段名
    if (Array.isArray(res)) {
      navSections.value = res
    } else if (res && typeof res === 'object') {
      navSections.value = Object.entries(res).map(([_key, val]: [string, any]) => ({
        title: val.name ?? _key,
        items: (val.items ?? []).map((item: any) => ({
          title: item.name,
          path: item.url,
          icon: item.icon,
          permission: item.code,
        })),
      }))
    }
  }

  async function init() {
    if (loaded.value) return
    try {
      await fetchUser()
      // 导航数据不阻塞首屏渲染，后台加载完成后侧边栏自动更新
      fetchNavSections().catch((e) => {
        console.error('[Auth] 导航数据加载失败:', e)
      })
    } finally {
      loaded.value = true
    }
  }

  function hasPermission(code: string): boolean {
    if (user.value?.isSuper) return true
    return user.value?.permissions?.includes(code) ?? false
  }

  function logout() {
    user.value = null
    navSections.value = []
    loaded.value = false
  }

  return { user, navSections, loaded, isLoggedIn, init, fetchUser, fetchNavSections, hasPermission, logout }
})
