/**
 * useVersionActions — 版本动作域（批次 2-3 拆分自 usePatternRoomPartActions）
 *
 * 承载版本创建弹窗、版本切换、是否当前版本判定。
 * 函数逻辑自 usePatternRoomPartActions.ts 原样搬移。
 */
import { ref } from 'vue'
import { toast } from '@/composables/useToast'
import { computed } from 'vue'
import type { PatternRoomActionContext } from './usePartActions'

export function useVersionActions(ctx: PatternRoomActionContext) {
  const { selectedProjectId, projectHook, partHook, versionHook, roleHook } = ctx

  /** 版本创建弹窗可见性 */
  const versionCreateVisible = ref(false)

  function openCreateVersionDialog() {
    if (!ctx.canManage.value) {
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

  return {
    versionCreateVisible,
    openCreateVersionDialog,
    isCurrentVersion,
    onSwitchVersion,
    onVersionCreateConfirm,
  }
}
