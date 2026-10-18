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
import { getErrorStatus } from '@/types/errors'
import { resolveSamplingErrorMessage } from './useSamplingErrors'

/** 角色操作的 409/404 专用文案（5 处调用共用，避免逐处复制漂移） */
const ROLE_ERROR_OPTS = {
  conflict: '该角色已被他人更新，请刷新后重试',
  notFound: '角色不存在，可能已被删除',
} as const

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
  /**
   * 最近一次失败的状态码。
   *
   * 本 hook 的写操作在内部 catch 后统一返回 null，调用方拿不到异常对象；
   * 而 403 已由 axios 拦截器统一提示，调用方若只凭 error 文案再弹一次 toast
   * 就会同一次失败弹两条。故把状态码一并暴露，让调用方复用同一套 403 抑制口径。
   */
  const errorStatus = ref<number | undefined>(undefined)

  /** 竞态保护：快速切换项目时忽略旧响应 */
  let _requestId = 0

  /** 加载角色列表 */
  async function fetchRoles(id: number): Promise<void> {
    const reqId = ++_requestId
    loading.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.listRoles(id)
      if (reqId !== _requestId) return
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
      if (reqId !== _requestId) return
      console.error('[useSamplingRole] 查询角色列表失败:', e)
      const message = resolveSamplingErrorMessage(e, '加载角色列表失败', ROLE_ERROR_OPTS)
      error.value = message
      // 调用方靠 errorStatus 抑制 403 的重复 toast；不写会沿用上一次操作的状态码
      errorStatus.value = getErrorStatus(e)
      roles.value = []
    } finally {
      if (reqId === _requestId) loading.value = false
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
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.createRole(projectId.value, { role_name: roleName })
      // 刷新角色列表
      await fetchRoles(projectId.value)
      return res
    } catch (e) {
      console.error('[useSamplingRole] 新增角色失败:', e)
      const message = resolveSamplingErrorMessage(e, '新增角色失败', ROLE_ERROR_OPTS)
      error.value = message
      errorStatus.value = getErrorStatus(e)
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 改名 */
  async function renameRole(roleId: number, newName: string, version: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.updateRole(roleId, { role_name: newName, version })
      // 刷新角色列表
      if (projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 改名角色失败:', e)
      const message = resolveSamplingErrorMessage(e, '改名失败', ROLE_ERROR_OPTS)
      const status = getErrorStatus(e)
      // 乐观锁冲突：自动刷新列表。fetchRoles 入口会重置 error/errorStatus，
      // 故先取本地副本、刷新完再回写，否则冲突文案被冲掉、调用方只能拿到兜底文案
      if (status === 409 && projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      error.value = message
      errorStatus.value = status
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 设置角色最终版本（current_version） */
  async function setRoleCurrentVersion(roleId: number, versionNo: string, version: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.updateRole(roleId, { current_version: versionNo, version })
      // 局部 patch：仅更新对应角色的 current_version 与乐观锁版本号，避免全量 fetchRoles 闪烁。
      // version 回写用于二次设置最终版本时携带新版本号，避免 409。
      const idx = roles.value.findIndex((r) => r.id === roleId)
      if (idx > -1) {
        roles.value[idx] = {
          ...roles.value[idx]!,
          current_version: versionNo,
          version: res.version ?? (roles.value[idx]!.version + 1),
        }
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 设置角色最终版本失败:', e)
      const message = resolveSamplingErrorMessage(e, '设置最终版本失败', ROLE_ERROR_OPTS)
      const status = getErrorStatus(e)
      // 乐观锁冲突：自动刷新列表。fetchRoles 入口会重置 error/errorStatus，
      // 故先取本地副本、刷新完再回写，否则冲突文案被冲掉
      if (status === 409 && projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      error.value = message
      errorStatus.value = status
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 删除角色（角色一律可删除，其部位布料与版本快照级联删除） */
  async function deleteRole(roleId: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.deleteRole(roleId)
      // 刷新角色列表
      if (projectId.value != null) {
        await fetchRoles(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingRole] 删除角色失败:', e)
      const message = resolveSamplingErrorMessage(e, '删除角色失败', ROLE_ERROR_OPTS)
      error.value = message
      errorStatus.value = getErrorStatus(e)
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
    errorStatus.value = undefined
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
    errorStatus,
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
