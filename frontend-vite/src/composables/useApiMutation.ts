import { useQueryClient } from '@tanstack/vue-query'
import { showToast } from '@/composables/useToast'

/**
 * 通用 API mutation composable
 * - 自动成功/失败提示
 * - 自动 invalidation
 */
export function useApiMutation<TData = unknown, TVariables = unknown>(
  mutationFn: (vars: TVariables) => Promise<TData>,
  options?: {
    invalidateKeys?: string[]
    successMsg?: string
    errorMsg?: string
  },
) {
  const queryClient = useQueryClient()

  async function mutate(variables: TVariables) {
    try {
      const result = await mutationFn(variables)
      if (options?.successMsg !== undefined) {
        showToast(options.successMsg, 'success')
      }
      if (options?.invalidateKeys) {
        for (const key of options.invalidateKeys) {
          queryClient.invalidateQueries({ queryKey: [key] })
        }
      }
      return result
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || options?.errorMsg || '操作失败'
      showToast(msg, 'error')
      throw err
    }
  }

  return { mutate }
}
