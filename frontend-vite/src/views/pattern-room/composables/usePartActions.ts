/**
 * usePartActions — 部位动作域（批次 2-3 拆分自 usePatternRoomPartActions）
 *
 * 承载部位批量创建、内联编辑保存、复制/删除部位版本、设置最终版本。
 * 函数逻辑自 usePatternRoomPartActions.ts 原样搬移。
 */
import { ref, type Ref } from 'vue'
import { toast } from '@/composables/useToast'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternRoomApi } from '@/api/patternRoom'
import type { BatchPartCreateRequest, PartDetail, PartUpdateRequest } from '@/api/patternRoom'
import { getErrorMessage } from '@/types/errors'
import type { useSamplingProject } from './useSamplingProject'
import type { useSamplingPart } from './useSamplingPart'
import type { useSamplingVersion } from './useSamplingVersion'
import type { useSamplingRole } from './useSamplingRole'

type ProjectHook = ReturnType<typeof useSamplingProject>
type PartHook = ReturnType<typeof useSamplingPart>
type VersionHook = ReturnType<typeof useSamplingVersion>
type RoleHook = ReturnType<typeof useSamplingRole>
type ConfirmDialog = ReturnType<typeof useConfirmDialog>

/** 板房动作域共享上下文（各子 hook 同构入参） */
export interface PatternRoomActionContext {
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

export function usePartActions(ctx: PatternRoomActionContext) {
  const { canManage, confirmDialog, selectedProjectId, projectHook, partHook, roleHook } = ctx

  /** 部位批量创建弹窗可见性 */
  const partFormVisible = ref(false)

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

  /** 复制部位版本：在该部位名称下新增一个版本号 +1 的空白记录 */
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

  return {
    partFormVisible,
    openCreatePartDialog,
    onPartSubmitBatch,
    onSetFinalVersion,
    onCopyPartVersion,
    onSaveEdit,
    onDeleteVersion,
  }
}
