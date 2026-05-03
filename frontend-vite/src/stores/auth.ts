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
    const res = await authApi.me()
    const raw = res.user ?? res
    user.value = {
      id: raw.user_id ?? raw.id,
      username: raw.username,
      isSuper: raw.is_super ?? raw.isSuper ?? false,
      permissions: raw.permissions ?? [],
    }
    return user.value
  }

  type NavApiItem = { name: string; url: string; icon?: string; code: string; permission_codes: string[] }

  async function fetchNavSections() {
    const res = await dashboardApi.navSections()
    if (Array.isArray(res)) {
      navSections.value = res
    } else if (res && typeof res === 'object') {
      navSections.value = Object.entries(res).map(([_key, val]) => ({
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

  function hasAnyPermission(codes: string[]): boolean {
    if (user.value?.isSuper) return true
    return codes.some((code) => user.value?.permissions?.includes(code) ?? false)
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
    user.value = null
    navSections.value = []
    loaded.value = false
  }

  return { user, navSections, filteredNavSections, loaded, isLoggedIn, init, fetchUser, fetchNavSections, hasPermission, hasAnyPermission, logout }
})
