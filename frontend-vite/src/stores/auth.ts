import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, dashboardApi } from '@/api'
import type { User, NavSection } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const navSections = ref<NavSection[]>([])
  const loaded = ref(false)

  const isLoggedIn = computed(() => !!user.value)
  const permissionSet = computed(() => new Set(user.value?.permissions ?? []))

  async function fetchUser() {
    const res = await authApi.me()
    const raw = res.user ?? res
    user.value = {
      id: raw.user_id ?? raw.id ?? 0,
      username: raw.username,
      is_super: raw.is_super ?? false,
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
      navSections.value = Object.entries(res)
        .filter(([_key, val]) => val && typeof val === 'object' && !Array.isArray(val))
        .map(([_key, val]: [string, any]) => ({
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

  async function init(force = false) {
    if (loaded.value && !force) return
    try {
      await fetchUser()
      fetchNavSections().catch((e) => {
        console.error('[Auth] 导航数据加载失败:', e)
      })
    } catch (error) {
      loaded.value = false
      throw error
    } finally {
      if (user.value) loaded.value = true
    }
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
    user.value = null
    navSections.value = []
    loaded.value = false
    if (import.meta.env.VITE_CAPACITOR) {
      localStorage.removeItem('access_token')
    }
  }

  return { user, navSections, filteredNavSections, loaded, isLoggedIn, init, fetchUser, fetchNavSections, hasPermission, hasAnyPermission, logout }
})
