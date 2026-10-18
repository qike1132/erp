/**
 * usePatternRoomPartActions — 部位/版本/角色操作编排 Hook
 *
 * 封装部位批量创建弹窗、设置最终版本、复制/删除部位版本、
 * 内联编辑保存、角色 TAB 切换与增删。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { nextTick, ref, type Ref } from 'vue'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternRoomApi } from '@/api/patternRoom'
import type { BatchPartCreateRequest, PartDetail, PartUpdateRequest } from '@/api/patternRoom'
import { showToast } from '@/composables/useToast'
import { getErrorStatus } from '@/types/errors'
import { resolveSamplingErrorMessage } from './useSamplingErrors'
import { createEmptyEditData, PART_EDIT_FIELDS, usePartInlineEdit, type PartEditData } from './usePartInlineEdit'

/** 403 已由 axios 拦截器统一提示，避免同一次失败弹两条 toast。 */
function toastActionError(e: unknown, fallback: string) {
  if (getErrorStatus(e) === 403) return
  showToast(resolveSamplingErrorMessage(e, fallback), 'error')
}
import { createManageGuard } from './useManageGuard'
import type { useSamplingProject } from './useSamplingProject'
import type { useSamplingPart } from './useSamplingPart'
import type { useSamplingVersion } from './useSamplingVersion'
import type { useSamplingRole } from './useSamplingRole'

type ProjectHook = ReturnType<typeof useSamplingProject>
type PartHook = ReturnType<typeof useSamplingPart>
type VersionHook = ReturnType<typeof useSamplingVersion>
type RoleHook = ReturnType<typeof useSamplingRole>
type ConfirmDialog = ReturnType<typeof useConfirmDialog>

/** 角色删除入参（与 RoleTabs 组件 emit 结构一致） */
interface RoleRemovePayload {
  id: number
  role_name: string
}

interface UsePatternRoomPartActionsOptions {
  /** 是否有管理权限 */
  canManage: Ref<boolean>
  /** 确认弹窗（与壳层共享同一实例） */
  confirmDialog: ConfirmDialog
  /** 当前选中项目 ID */
  selectedProjectId: Ref<number | null>
  /** 项目 CRUD Hook */
  projectHook: ProjectHook
  /** 部位 Hook */
  partHook: PartHook
  /** 版本 Hook */
  versionHook: VersionHook
  /** 角色 Hook */
  roleHook: RoleHook
}

export function usePatternRoomPartActions(options: UsePatternRoomPartActionsOptions) {
  const {
    canManage,
    confirmDialog,
    selectedProjectId,
    projectHook,
    partHook,
    versionHook,
    roleHook,
  } = options

  /** 统一写权限守卫（替代 9 处重复的 canManage 检查） */
  const requireManage = createManageGuard(canManage)

  /** 部位批量创建弹窗可见性 */
  const partFormVisible = ref(false)

  function openCreatePartDialog() {
    if (!requireManage()) return
    partFormVisible.value = true
  }

  async function onPartSubmitBatch(data: BatchPartCreateRequest) {
    if (!selectedProjectId.value) return
    // 提交守卫：防止请求进行中重复提交（PartFormDialog 的提交按钮依赖该状态禁用）
    if (partHook.submitting.value) return
    partHook.submitting.value = true
    try {
      const res = await patternRoomApi.batchCreateParts(
        selectedProjectId.value,
        data,
        roleHook.currentRoleId.value ?? undefined,
      )
      if (res.success) {
        partFormVisible.value = false
        if (selectedProjectId.value) {
          await Promise.all([
            projectHook.fetchDetail(selectedProjectId.value),
            partHook.fetchPartsByVersion(
              selectedProjectId.value,
              roleHook.currentRoleId.value ?? undefined,
            ),
          ])
        }
      }
    } catch (e) {
      console.error('[PatternRoomView] 批量创建部位失败:', e)
      // 2026-10-17 审计 AUD-12：全局拦截器对非 401/403 无用户兜底，
      // catch 里只打 console 等于「假成功」——用户看不到任何失败信号。
      toastActionError(e, '批量创建部位失败')
    } finally {
      partHook.submitting.value = false
    }
  }

  /** 设置最终版本：更新当前角色的 current_version */
  async function onSetFinalVersion(versionNo: string) {
    if (!requireManage()) return
    if (!selectedProjectId.value) return
    const currentRole = roleHook.getCurrentRole()
    if (!currentRole) return
    try {
      const res = await roleHook.setRoleCurrentVersion(currentRole.id, versionNo, currentRole.version)
      if (res) {
        // 部位数据本身未变化，仅本地更新最终版本号，
        // 避免 fetchPartsByVersion 的 loading 态与数据整体替换导致整表闪烁
        partHook.setFinalVersion(versionNo)
      } else {
        // 2026-10-18 OCR 评审：setRoleCurrentVersion 内部吞异常返回 null，
        // 上面的 catch 不可达；必须显式处理 null，否则失败被当成功。
        // 复用 toastActionError 的 403 抑制口径（403 已由拦截器提示），
        // 否则同一次失败会弹两条 toast。
        if (roleHook.errorStatus.value !== 403) {
          showToast(roleHook.error.value ?? '设置最终版本失败，请重试', 'error')
        }
      }
    } catch (e) {
      console.error('[PatternRoomView] 设置最终版本失败:', e)
      toastActionError(e, '设置最终版本失败')
    }
  }

  /** 复制部位版本：在该部位名称下新增一个版本号 +1 的空白记录，
   *  并将新版本设为该角色最终版本，随后自动进入新记录的编辑态 */
  async function onCopyPartVersion(part: PartDetail) {
    if (!requireManage()) return
    if (part.id == null) return
    try {
      const res = await patternRoomApi.copyPartVersion(part.id)
      if (res.success) {
        // 新版本默认成为最终版本：必须先写库再拉取部位数据，
        // 否则 parts-by-version 返回的 final_version 仍是旧版本，
        // 折叠态会继续只显示旧版本行，新版本不可见
        const currentRole = roleHook.getCurrentRole()
        if (currentRole && res.version_no) {
          const roleRes = await roleHook.setRoleCurrentVersion(
            currentRole.id,
            res.version_no,
            currentRole.version,
          )
          if (!roleRes) {
            // 2026-10-18 OCR 评审：设最终版本失败时不得继续进入编辑态（假成功）；
            // 但复制接口已成功落库，必须刷新列表，避免用户重试产生重复版本。
            // 403 已由 axios 拦截器统一提示，此处需抑制，否则双弹。
            if (roleHook.errorStatus.value !== 403) {
              showToast(
                roleHook.error.value ?? `版本 ${res.version_no} 已复制，但设为最终版本失败，请手动设置`,
                'error',
              )
            }
            if (selectedProjectId.value) {
              await partHook.fetchPartsByVersion(
                selectedProjectId.value,
                roleHook.currentRoleId.value ?? undefined,
              )
            }
            return
          }
        }
        if (selectedProjectId.value) {
          await partHook.fetchPartsByVersion(
            selectedProjectId.value,
            roleHook.currentRoleId.value ?? undefined,
          )
        }
        // fetchPartsByVersion 整体替换 partsByVersion 会触发 usePartInlineEdit 的
        // watch 清空 editingPartId，必须等 watch 冲刷完（nextTick）再设置，否则被冲掉
        if (res.id != null) {
          await nextTick()
          editingPartId.value = res.id
          Object.assign(editForm, createEmptyEditData())
        }
      }
    } catch (e) {
      console.error('[PatternRoomView] 复制部位版本失败:', e)
      toastActionError(e, '复制部位版本失败')
    }
  }

  /**
   * 内联编辑状态（editingPartId / editForm）与 start/save/cancel 编排。
   * 行组件 PartsVersionRowV2 仅 emit (part)，表单数据从 editForm 读取。
   */
  const {
    editingPartId,
    editForm,
    startEdit,
    saveEdit,
    cancelEdit,
  } = usePartInlineEdit(
    partHook.partsByVersion,
    selectedProjectId,
    roleHook.currentRoleId,
    onSaveEditData,
  )

  function onStartEdit(part: PartDetail) {
    if (!requireManage()) return
    startEdit(part)
  }

  function onCancelEdit() {
    cancelEdit()
  }

  /** 保存内联编辑：退出编辑态并将当前表单数据提交到 onSaveEditData */
  function onSaveEdit(part: PartDetail) {
    if (!requireManage()) return
    if (part.id == null) return
    saveEdit(part)
  }

  /** 保存内联编辑的载荷处理（表单数据由 usePartInlineEdit 注入） */
  async function onSaveEditData(part: PartDetail, data: PartEditData) {
    if (!requireManage()) return
    if (part.id == null) return
    try {
      // 载荷与本地 patch 均从字段元数据派生，新增字段无需改动此处
      const payload: PartUpdateRequest = {
        version: part.version ?? 0,
        ...Object.fromEntries(PART_EDIT_FIELDS.map((f) => [f.key, data[f.key] || null])),
      }
      const res = await patternRoomApi.updatePart(part.id, payload)
      if (res.success) {
        partHook.patchPart(part.id, {
          ...Object.fromEntries(PART_EDIT_FIELDS.map((f) => [f.key, data[f.key] || ''])),
          // 回写乐观锁新版本号，避免第二次编辑携带旧 version 触发 409
          version: res.version ?? (part.version + 1),
        })
      }
    } catch (e) {
      console.error('[PatternRoomView] 保存部位编辑失败:', e)
      const status = getErrorStatus(e)
      if (status !== 403) {
        showToast(
          resolveSamplingErrorMessage(e, '保存失败', {
            conflict: '该部位已被他人修改，已刷新为最新数据，请重新编辑',
          }),
          'error',
        )
      }
      // 409 乐观锁冲突：局部 patch 未更新 version，需全量刷新获取最新数据
      if (getErrorStatus(e) === 409 && selectedProjectId.value) {
        await partHook.fetchPartsByVersion(
          selectedProjectId.value,
          roleHook.currentRoleId.value ?? undefined,
        )
      }
    }
  }

  /** 删除部位版本 */
  async function onDeleteVersion(part: PartDetail) {
    if (!requireManage()) return
    if (part.id == null) return
    // 删除最终版本时使用加强提示文案
    const isFinalVersion = !!part.version_no && part.version_no === partHook.finalVersion.value
    const ok = isFinalVersion
      ? await confirmDialog.confirm(
          '删除最终版本',
          `版本 ${part.version_no} 是当前项目的最终版本，删除后将无法再设为最终版，请确认是否继续。`,
          'danger',
        )
      : await confirmDialog.confirm(
          '确认删除该部位版本？',
          `部位「${part.part_name}」版本 ${part.version_no ?? '-'}，删除后不可恢复。`,
          'danger',
        )
    if (!ok) return
    try {
      const res = await patternRoomApi.deletePart(part.id)
      if (res.success) {
        partHook.removePartLocal(part.id)
      }
    } catch (e) {
      console.error('[PatternRoomView] 删除部位版本失败:', e)
      toastActionError(e, '删除部位版本失败')
    }
  }

  /** 是否当前版本（选中版本为项目最新版本） */
  const isCurrentVersion = computed(() => {
    const proj = projectHook.currentProject.value
    const detail = versionHook.versionDetail.value
    if (!proj || !detail) return false
    return detail.version_no === proj.current_version
  })

  function onSwitchVersion(versionId: number) {
    versionHook.fetchVersionDetail(versionId)
  }

  function onSelectRole(roleId: number) {
    roleHook.setCurrentRole(roleId)
    // partHook / versionHook 会自动 watch currentRoleId 重新加载
  }

  async function onAddRole(roleName: string) {
    if (!requireManage()) return
    if (!selectedProjectId.value) return
    // roleHook.createRole 内部吞异常返回 null，不会抛到这里；
    // 若不再判一次，失败就是「假成功」——输入框消失、标签没出现、无任何提示。
    // 403 已由 axios 拦截器提示，走同一套抑制口径避免双弹。
    const res = await roleHook.createRole(roleName)
    if (!res && roleHook.errorStatus.value !== 403) {
      showToast(roleHook.error.value ?? '新增角色失败，请重试', 'error')
    }
  }

  async function onRemoveRole(role: RoleRemovePayload) {
    if (!requireManage()) return
    const ok = await confirmDialog.confirm(
      '确认删除该角色？',
      `角色「${role.role_name}」下所有部位布料和版本快照将被级联删除，且不可恢复。`,
      'danger',
    )
    if (!ok) return
    // 同上：deleteRole 吞异常返回 null，失败对用户不可见（假成功）
    const res = await roleHook.deleteRole(role.id)
    if (!res && roleHook.errorStatus.value !== 403) {
      showToast(roleHook.error.value ?? '删除角色失败，请重试', 'error')
    }
    // roleHook.fetchRoles 已自动调用，会自动切换 currentRoleId 到第一个角色
    // partHook 会自动 watch 重新加载
  }

  return {
    partFormVisible,
    editingPartId,
    editForm,
    openCreatePartDialog,
    onPartSubmitBatch,
    onSetFinalVersion,
    onCopyPartVersion,
    onSaveEdit,
    onStartEdit,
    onCancelEdit,
    onDeleteVersion,
    isCurrentVersion,
    onSwitchVersion,
    onSelectRole,
    onAddRole,
    onRemoveRole,
  }
}
