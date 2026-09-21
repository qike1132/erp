/**
 * 打样模块统一的写操作权限守卫（CP-3）
 *
 * 背景：`if (!canManage.value) { toast.warning('无操作权限'); return }` 原先在
 * usePatternRoomPartActions / usePatternRoomProjectActions / usePatternRoomPatternMakers
 * 中重复 17 次。权限文案或策略一旦调整需逐处同步，且极易漏改。
 *
 * 用法：
 * ```ts
 * const requireManage = createManageGuard(canManage)
 * function onDoSomething() {
 *   if (!requireManage()) return
 *   // ...业务逻辑
 * }
 * ```
 */
import type { Ref } from 'vue'
import { toast } from '@/composables/useToast'

/** 无写权限时的统一提示文案 */
export const NO_PERMISSION_MESSAGE = '无操作权限'

/**
 * 基于 canManage 创建守卫函数。
 * @returns 有权限返回 true；无权限时 toast 提示并返回 false
 */
export function createManageGuard(canManage: Ref<boolean>): () => boolean {
  return function requireManage(): boolean {
    if (canManage.value) return true
    toast.warning(NO_PERMISSION_MESSAGE)
    return false
  }
}
