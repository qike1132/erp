/**
 * useRoleActions — 角色动作域（批次 2-3 拆分自 usePatternRoomPartActions）
 *
 * 承载角色 TAB 切换与增删。
 * 函数逻辑自 usePatternRoomPartActions.ts 原样搬移。
 */
import { toast } from '@/composables/useToast'
import type { PatternRoomActionContext } from './usePartActions'

/** 角色删除入参（与 RoleTabs 组件 emit 结构一致） */
export interface RoleRemovePayload {
  id: number
  role_name: string
  is_default: boolean
}

export function useRoleActions(ctx: PatternRoomActionContext) {
  const { canManage, confirmDialog, selectedProjectId, roleHook } = ctx

  function onSelectRole(roleId: number) {
    roleHook.setCurrentRole(roleId)
    // partHook / versionHook 会自动 watch currentRoleId 重新加载
  }

  async function onAddRole(roleName: string) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (!selectedProjectId.value) return
    const res = await roleHook.createRole(roleName)
    if (res) {
      toast.success('角色创建成功')
    } else {
      toast.error(roleHook.error.value || '创建角色失败')
    }
  }

  async function onRemoveRole(role: RoleRemovePayload) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (role.is_default) {
      toast.warning('默认角色不可删除')
      return
    }
    const ok = await confirmDialog.confirm(
      '确认删除该角色？',
      `角色「${role.role_name}」下所有部位布料和版本快照将被级联删除，且不可恢复。`,
      'danger',
    )
    if (!ok) return
    const res = await roleHook.deleteRole(role.id)
    if (res) {
      toast.success('删除成功')
      // roleHook.fetchRoles 已自动调用，会自动切换 currentRoleId 到第一个角色
      // partHook 会自动 watch 重新加载
    } else {
      toast.error(roleHook.error.value || '删除角色失败')
    }
  }

  return {
    onSelectRole,
    onAddRole,
    onRemoveRole,
  }
}
