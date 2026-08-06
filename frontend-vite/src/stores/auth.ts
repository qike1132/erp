import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, dashboardApi } from '@/api'
import type { User, NavSection } from '@/types'
import { removeAccessToken } from '@/utils/secureStorage'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const navSections = ref<NavSection[]>([])
  const loaded = ref(false)
  let _initPromise: Promise<void> | null = null

  const isLoggedIn = computed(() => !!user.value)
  const permissionSet = computed(() => new Set(user.value?.permissions ?? []))

  async function fetchUser() {
    const res = await authApi.me()
    const raw = res.user ?? res
    user.value = {
      id: raw.user_id ?? raw.id ?? 0,
      username: raw.username,
      is_super: raw.is_super ?? false,
      factory: raw.factory ?? null,
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
    // 防止并发调用：多个导航同时触发时复用同一个 Promise
    if (_initPromise && !force) return _initPromise

    _initPromise = (async () => {
      try {
        await fetchUser()
        // 导航数据加载失败不应阻止用户进入系统
        await fetchNavSections().catch((e) => {
          console.error('[Auth] 导航数据加载失败:', e)
        })
      } catch (error) {
        loaded.value = false
        throw error
      } finally {
        if (user.value) loaded.value = true
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
    user.value = null
    navSections.value = []
    loaded.value = false
    if (import.meta.env.VITE_CAPACITOR) {
      removeAccessToken()
    }
  }

  return { user, navSections, filteredNavSections, loaded, isLoggedIn, init, fetchUser, fetchNavSections, hasPermission, hasAnyPermission, logout }
})
