import { useAuthStore } from '@/stores/auth'

/**
 * 权限判断 composable
 */
export function usePermission() {
  const authStore = useAuthStore()

  function hasPermission(code: string): boolean {
    return authStore.hasPermission(code)
  }

  return { hasPermission }
}
