/**
 * usePatternRoomPartActions — 部位/版本/角色操作编排 Hook
 *
 * 封装部位批量创建弹窗、版本创建弹窗、设置最终版本、复制/删除部位版本、
 * 内联编辑保存、角色 TAB 切换与增删。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, nextTick, type Ref } from 'vue'
import { toast } from '@/composables/useToast'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternRoomApi } from '@/api/patternRoom'
import type { BatchPartCreateRequest, PartDetail, PartUpdateRequest } from '@/api/patternRoom'
import { getErrorMessage } from '@/types/errors'
import type { useSamplingProject } from './useSamplingProject'
import type { useSamplingPart } from './useSamplingPart'
import type { useSamplingVersion } from './useSamplingVersion'
import type { useSamplingRole } from './useSamplingRole'
import { usePartInlineEdit, type PartEditData } from './usePartInlineEdit'

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

  /** 部位批量创建弹窗可见性 */
  const partFormVisible = ref(false)
  /** 版本创建弹窗可见性 */
  const versionCreateVisible = ref(false)

  /**
   * 复制版本后待自动编辑的目标版本号。
   * 复制 T2 → T3 后，自动打开 T3 的修改模式；保存成功后自动将 T3 设为最终版本。
   */
  const pendingCopyVersionNo = ref<string | null>(null)

  /** 内联编辑状态：上移到此 Composable，复制处理可在刷新后自动触发编辑 */
  const {
    editingPartId,
    editForm,
    startEdit,
    cancelEdit,
    saveEdit,
  } = usePartInlineEdit(
    partHook.partsByVersion,
    selectedProjectId,
    roleHook.currentRoleId,
    onSaveEdit,
  )

  function openCreatePartDialog() {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    partFormVisible.value = true
  }

  async function onPartSubmitBatch(data: BatchPartCreateRequest) {
    if (!selectedProjectId.value) return
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
      toast.error('批量创建部位失败')
    }
  }

  /** 设置最终版本：更新当前角色的 current_version */
  async function onSetFinalVersion(versionNo: string) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
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
      toast.error('设置最终版本失败')
    }
  }

  /** 复制部位版本：新增版本号 +1 的空白记录，并自动打开修改模式、保存后设为最终版本 */
  async function onCopyPartVersion(part: PartDetail) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法复制版本')
      return
    }
    try {
      const res = await patternRoomApi.copyPartVersion(part.id)
      if (res.success) {
        const newVersionNo = res.version_no ?? null
        toast.success(res.message || `已复制版本 ${newVersionNo ?? ''}`)
        if (selectedProjectId.value) {
          await partHook.fetchPartsByVersion(
            selectedProjectId.value,
            roleHook.currentRoleId.value ?? undefined,
          )
        }
        if (newVersionNo) {
          pendingCopyVersionNo.value = newVersionNo
          // 局部设为最终版本，使新版本行默认展开被选中，便于随后自动进入修改模式
          partHook.setFinalVersion(newVersionNo)
        }
        // 等 partsByVersion 刷新与折叠计算完成后，自动打开新版本行的修改模式
        await nextTick()
        const newPart = partHook.partsByVersion.value.find(
          (p) => p.version_no === newVersionNo && p.part_name === part.part_name,
        )
        if (newPart?.id != null) {
          startEdit(newPart)
        }
      } else {
        toast.error(res.message || '复制版本失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 复制部位版本失败:', e)
      toast.error(getErrorMessage(e, '复制部位版本失败'))
    }
  }

  /** 保存内联编辑 */
  async function onSaveEdit(
    part: PartDetail,
    data: { supplier_name: string; fabric_name: string; fabric_color_no: string },
  ) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (part.id == null) {
      toast.warning('该记录为历史快照，无法编辑')
      return
    }
    try {
      const payload: PartUpdateRequest = {
        version: part.version ?? 0,
        supplier_name: data.supplier_name || null,
        fabric_name: data.fabric_name || null,
        fabric_color_no: data.fabric_color_no || null,
      }
      const res = await patternRoomApi.updatePart(part.id, payload)
      if (res.success) {
        toast.success('保存成功')
        partHook.patchPart(part.id, {
          supplier_name: data.supplier_name || '',
          fabric_name: data.fabric_name || '',
          fabric_color_no: data.fabric_color_no || '',
        })
        // 若保存的正是本次复制生成的新版本，自动将其设为最终版本
        if (pendingCopyVersionNo.value && part.version_no === pendingCopyVersionNo.value) {
          pendingCopyVersionNo.value = null
          await onSetFinalVersion(part.version_no!)
        }
      } else {
        toast.error(res.message || '保存失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 保存部位编辑失败:', e)
      const status = (e as { response?: { status?: number } })?.response?.status
      const errMsg = status === 409 ? '数据已被他人更新，请刷新后重试' : '保存失败'
      toast.error(errMsg)
      // 409 乐观锁冲突：局部 patch 未更新 version，需全量刷新获取最新数据
      if (status === 409 && selectedProjectId.value) {
        await partHook.fetchPartsByVersion(
          selectedProjectId.value,
          roleHook.currentRoleId.value ?? undefined,
        )
      }
    }
  }

  /** 删除部位版本 */
  async function onDeleteVersion(part: PartDetail) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
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
      toast.error('删除部位版本失败')
    }
  }

  function openCreateVersionDialog() {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    versionCreateVisible.value = true
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

  async function onVersionCreateConfirm(reason: string | null) {
    const res = await versionHook.createVersion(reason ?? undefined)
    if (res) {
      toast.success(res.message || `已创建版本 ${res.version_no ?? ''}`)
      versionCreateVisible.value = false
      // 并行刷新角色列表 + 项目详情（原串行 await）
      if (selectedProjectId.value) {
        await Promise.all([
          roleHook.fetchRoles(selectedProjectId.value),
          projectHook.fetchDetail(selectedProjectId.value),
        ])
      }
      // 空快照提示
      if (partHook.partsByVersion.value.length === 0) {
        toast.warning('当前无部位布料信息，已创建空版本，建议先维护部位布料')
      }
    } else {
      toast.error(versionHook.error.value || '创建新版本失败')
    }
  }

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
    partFormVisible,
    versionCreateVisible,
    openCreatePartDialog,
    onPartSubmitBatch,
    onSetFinalVersion,
    onCopyPartVersion,
    onSaveEdit,
    onDeleteVersion,
    openCreateVersionDialog,
    isCurrentVersion,
    onSwitchVersion,
    onVersionCreateConfirm,
    onSelectRole,
    onAddRole,
    onRemoveRole,
    editingPartId,
    editForm,
    startEdit,
    cancelEdit,
    saveEdit,
  }
}
