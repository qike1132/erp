/**
 * usePatternRoomPartActions — 部位/版本/角色操作编排 Hook
 *
 * 封装部位批量创建弹窗、设置最终版本、复制/删除部位版本、
 * 内联编辑保存、角色 TAB 切换与增删。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, type Ref } from 'vue'
import { toast } from '@/composables/useToast'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternRoomApi } from '@/api/patternRoom'
import type { BatchPartCreateRequest, PartDetail, PartUpdateRequest } from '@/api/patternRoom'
import { getErrorMessage, getErrorStatus } from '@/types/errors'
import { PART_EDIT_FIELDS, usePartInlineEdit, type PartEditData } from './usePartInlineEdit'
import { createManageGuard } from './useManageGuard'
import { resolveSamplingErrorMessage } from './useSamplingErrors'
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
  is_default: boolean
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
        toast.success(res.message || `已创建 ${data.items.length} 个部位`)
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
      } else {
        toast.error(res.message || '批量创建失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 批量创建部位失败:', e)
      toast.error(getErrorMessage(e, '批量创建部位失败'))
    } finally {
      partHook.submitting.value = false
    }
  }

  /** 设置最终版本：更新当前角色的 current_version */
  async function onSetFinalVersion(versionNo: string) {
    if (!requireManage()) return
    if (!selectedProjectId.value) return
    const currentRole = roleHook.getCurrentRole()
    if (!currentRole) {
      toast.warning('请先选择角色')
      return
    }
    try {
      const res = await roleHook.setRoleCurrentVersion(currentRole.id, versionNo, currentRole.version)
      if (res) {
        toast.success(`已设置最终版本 ${versionNo}`)
        // 部位数据本身未变化，仅本地更新最终版本号，
        // 避免 fetchPartsByVersion 的 loading 态与数据整体替换导致整表闪烁
        partHook.setFinalVersion(versionNo)
      } else {
        toast.error(roleHook.error.value || '设置失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 设置最终版本失败:', e)
      toast.error(getErrorMessage(e, '设置最终版本失败'))
    }
  }

  /** 复制部位版本：在该部位名称下新增一个版本号 +1 的空白记录 */
  async function onCopyPartVersion(part: PartDetail) {
    if (!requireManage()) return
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法复制版本')
      return
    }
    try {
      const res = await patternRoomApi.copyPartVersion(part.id)
      if (res.success) {
        toast.success(res.message || `已复制版本 ${res.version_no ?? ''}`)
        if (selectedProjectId.value) {
          await partHook.fetchPartsByVersion(
            selectedProjectId.value,
            roleHook.currentRoleId.value ?? undefined,
          )
        }
      } else {
        toast.error(res.message || '复制版本失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 复制部位版本失败:', e)
      toast.error(getErrorMessage(e, '复制部位版本失败'))
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
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法编辑')
      return
    }
    saveEdit(part)
  }

  /** 保存内联编辑的载荷处理（表单数据由 usePartInlineEdit 注入） */
  async function onSaveEditData(part: PartDetail, data: PartEditData) {
    if (!requireManage()) return
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法编辑')
      return
    }
    try {
      // 载荷与本地 patch 均从字段元数据派生，新增字段无需改动此处
      const payload: PartUpdateRequest = {
        version: part.version ?? 0,
        ...Object.fromEntries(PART_EDIT_FIELDS.map((f) => [f.key, data[f.key] || null])),
      }
      const res = await patternRoomApi.updatePart(part.id, payload)
      if (res.success) {
        toast.success('保存成功')
        partHook.patchPart(part.id, {
          ...Object.fromEntries(PART_EDIT_FIELDS.map((f) => [f.key, data[f.key] || ''])),
          // 回写乐观锁新版本号，避免第二次编辑携带旧 version 触发 409
          version: res.version ?? (part.version + 1),
        })
      } else {
        toast.error(res.message || '保存失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 保存部位编辑失败:', e)
      // 统一走中心化解析：409 文案不变，非 409 时保留后端 detail（原先被泛化文案丢弃）
      toast.error(resolveSamplingErrorMessage(e, '保存失败'))
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
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法删除')
      return
    }
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
        toast.success(res.message || '删除成功')
        partHook.removePartLocal(part.id)
      } else {
        toast.error(res.message || '删除失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 删除部位版本失败:', e)
      toast.error(getErrorMessage(e, '删除部位版本失败'))
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
    const res = await roleHook.createRole(roleName)
    if (res) {
      toast.success('角色创建成功')
    } else {
      toast.error(roleHook.error.value || '创建角色失败')
    }
  }

  async function onRemoveRole(role: RoleRemovePayload) {
    if (!requireManage()) return
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
