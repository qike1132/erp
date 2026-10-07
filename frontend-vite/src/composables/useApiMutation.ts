import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import type { QueryClient } from '@tanstack/vue-query'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

/**
 * 通用 API mutation composable
 * - 自动成功/失败提示（失败文案经 getErrorMessage 提取，errorMsg 作兜底）
 * - 自动 invalidation：invalidateKeys 平铺键，或 invalidate 函数（utils/queryKeys
 *   的具名领域失效，OPT-09 起推荐后者——键集集中维护，避免各处手写清单漂移；
 *   历史上两起跨页不同步 bug 都是清单漏键）
 * - isSaving：in-flight 状态（按钮禁用），调用方不再手写 loading 样板
 *
 * 两个执行入口：
 *   mutate(vars) —— 既有契约：失败向上抛（toast 已弹出），由调用方自行处理
 *   run(vars)    —— OPT-09（2026-10-01）新增：失败不抛，返回 undefined 表示未成功，
 *                   适合「弹窗提交后按是否成功决定关不关」的场景
 *
 * 试点：views/report 的 useStockinEdit（2026-10-06 自 customer-order 迁入报表页）。
 * 其余直呼写接口的调用点按模块逐步迁移
 * （OPT-09）；全部迁移完成前不启用「view 禁入写函数」的 lint 规则。
 */
export function useApiMutation<TData = unknown, TVariables = unknown>(
  mutationFn: (vars: TVariables) => Promise<TData>,
  options?: {
    invalidateKeys?: string[]
    /** 领域失效函数（utils/queryKeys 的具名函数），可与 invalidateKeys 并用 */
    invalidate?: (client: QueryClient) => void
    successMsg?: string
    /** 失败兜底文案：静态串，或按本次入参动态生成（如 `${target}失败`） */
    errorMsg?: string | ((vars: TVariables) => string)
    /** 成功后的后续动作：关弹窗、重取列表等。await 完成后才结束 */
    onSuccess?: (result: TData) => void | Promise<void>
  },
) {
  const queryClient = useQueryClient()
  const isSaving = ref(false)

  function errorFallback(variables: TVariables): string {
    const raw = options?.errorMsg
    const fallback = typeof raw === 'function' ? raw(variables) : raw
    return fallback || '操作失败'
  }

  async function _execute(variables: TVariables): Promise<TData> {
    isSaving.value = true
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
      options?.invalidate?.(queryClient)
      await options?.onSuccess?.(result)
      return result
    } finally {
      isSaving.value = false
    }
  }

  /** 失败向上抛（toast 已弹出）——保持既有调用方契约 */
  async function mutate(variables: TVariables): Promise<TData> {
    try {
      return await _execute(variables)
    } catch (err: unknown) {
      showToast(getErrorMessage(err, errorFallback(variables)), 'error')
      throw err
    }
  }

  /** 失败不抛（toast 已弹出），返回 undefined 表示未成功 */
  async function run(variables: TVariables): Promise<TData | undefined> {
    try {
      return await _execute(variables)
    } catch (err: unknown) {
      showToast(getErrorMessage(err, errorFallback(variables)), 'error')
      return undefined
    }
  }

  return { mutate, run, isSaving }
}
