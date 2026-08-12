/**
 * useSamplingRole — 角色管理 Hook
 *
 * 封装角色列表查询、新增、改名、删除、切换当前角色的状态管理与 API 调用。
 * 接收响应式 projectId，watch 自动重新加载角色列表，并默认选中第一个角色（默认角色）。
 *
 * 各角色的部位布料数据完全独立：调用方监听 currentRoleId 变化重新拉取部位/版本数据。
 */
import { ref, watch, type Ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { RoleBrief, ActionResponse } from '@/api/patternRoom'
import { toast } from '@/composables/useToast'
import { getErrorMessage, getErrorStatus } from '@/types/errors'

function resolveRoleErrorMessage(err: unknown, fallback: string): string {
  const status = getErrorStatus(err)
  if (status === 409) return '该角色已被他人更新，请刷新后重试'
  if (status === 404) return '角色不存在，可能已被删除'
  if (status === 400) return getErrorMessage(err, '操作失败，请检查输入')
  return getErrorMessage(err, fallback)
}

export function useSamplingRole(projectId: Ref<number | null>) {
  /** 角色列表（按 sort_order 升序） */
  const roles = ref<RoleBrief[]>([])
  /** 当前选中角色 ID */
  const currentRoleId = ref<number | null>(null)
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（新增/改名/删除） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 加载角色列表 */
  async function fetchRoles(id: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.listRoles(id)
      roles.value = res.items ?? []
      // 默认选中第一个角色（sort_order=0 通常是默认角色）
      if (roles.value.length > 0 && currentRoleId.value == null) {
        currentRoleId.value = roles.value[0]!.id
      }
      // 若当前选中角色已不在列表中（被删除），切回第一个
      if (
        roles.value.length > 0
        && currentRoleId.value != null
        && !roles.value.some(r => r.id === currentRoleId.value)
      ) {
        currentRoleId.value = roles.value[0]!.id
      }
      // 若角色列表为空（异常情况），清空当前选中
      if (roles.value.length === 0) {
        currentRoleId.value = null
      }
    } catch (e) {
      console.error('[useSamplingRole] 查询角色列表失败:', e)
      const message = resolveRoleErrorMessage(e, '加载角色列表失败')
      error.value = message
      toast.error(message)
      roles.value = []
    } finally {
      loading.value = false
    }
  }

  /** 当前选中角色对象 */
  function getCurrentRole(): RoleBrief | null {
    return roles.value.find(r => r.id === currentRoleId.value) ?? null
  }

  /** 新增角色 */
  async function createRole(roleName: string): Promise<ActionResponse | null> {
    if (projectId.value == null) return null
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.createRole(projectId.value, { role_name: roleName })
      // 刷新角色列表
      await fetchRoles(projectId.value)
      return res
    } catch (e) {
      console.error('[useSamplingRole] 新增角色失败:', e)
      const message = resolveRoleErrorMessage(e, '新增角色失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 改名 */
  async function renameRole(roleId: number, newName: string, version: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.updateRole(roleId, { role_name: newName, version })
      // 刷新角色列表
      if (projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 改名角色失败:', e)
      const message = resolveRoleErrorMessage(e, '改名失败')
      error.value = message
      toast.error(message)
      // 乐观锁冲突：自动刷新列表
      if (getErrorStatus(e) === 409 && projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 设置角色最终版本（current_version） */
  async function setRoleCurrentVersion(roleId: number, versionNo: string, version: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.updateRole(roleId, { current_version: versionNo, version })
      if (projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 设置角色最终版本失败:', e)
      const message = resolveRoleErrorMessage(e, '设置最终版本失败')
      error.value = message
      toast.error(message)
      if (getErrorStatus(e) === 409 && projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 删除角色（默认角色不可删除，后端会拒绝） */
  async function deleteRole(roleId: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.deleteRole(roleId)
      // 刷新角色列表
      if (projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 删除角色失败:', e)
      const message = resolveRoleErrorMessage(e, '删除角色失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 切换当前角色 */
  function setCurrentRole(roleId: number): void {
    currentRoleId.value = roleId
  }

  /** 清空角色状态 */
  function clearRoles(): void {
    roles.value = []
    currentRoleId.value = null
    error.value = null
  }

  // watch projectId 自动重新加载角色列表
  watch(
    projectId,
    (newId, oldId) => {
      if (newId !== oldId) {
        // 切项目时先清空 currentRoleId，避免误用上一个项目的角色
        currentRoleId.value = null
      }
      if (newId != null) {
        fetchRoles(newId)
      } else {
        clearRoles()
      }
    },
    { immediate: true },
  )

  return {
    roles,
    currentRoleId,
    loading,
    submitting,
    error,
    fetchRoles,
    getCurrentRole,
    createRole,
    renameRole,
    setRoleCurrentVersion,
    deleteRole,
    setCurrentRole,
    clearRoles,
  }
}
