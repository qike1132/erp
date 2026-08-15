/**
 * usePatternRoomProjectActions — 打样项目 CRUD 弹窗编排 Hook
 *
 * 封装项目表单弹窗（新增/编辑）的打开与提交、
 * 项目卡片「完成/取消」状态操作、项目删除确认。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, type Ref } from 'vue'
import { toast } from '@/composables/useToast'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternRoomApi } from '@/api/patternRoom'
import type { ProjectCreateRequest, ProjectUpdateRequest } from '@/api/patternRoom'
import type { useCustomerSampling } from './useCustomerSampling'
import type { useSamplingProject } from './useSamplingProject'

type GroupHook = ReturnType<typeof useCustomerSampling>
type ProjectHook = ReturnType<typeof useSamplingProject>
type ConfirmDialog = ReturnType<typeof useConfirmDialog>

interface UsePatternRoomProjectActionsOptions {
  /** 是否有管理权限 */
  canManage: Ref<boolean>
  /** 确认弹窗（与壳层共享同一实例） */
  confirmDialog: ConfirmDialog
  /** 客户分组 Hook（操作成功后刷新分组列表） */
  groupHook: GroupHook
  /** 项目 CRUD Hook */
  projectHook: ProjectHook
  /** 当前选中项目 ID */
  selectedProjectId: Ref<number | null>
  /** 搜索关键词 */
  searchKeyword: Ref<string>
  /** 状态筛选 */
  statusFilter: Ref<string>
  /** 是否窄屏 */
  isNarrow: Ref<boolean>
  /** 窄屏抽屉展开状态 */
  drawerOpen: Ref<boolean>
  /** 弹窗当前选中的版师 ID */
  formPatternMakerId: Ref<number | null>
  /** 选中项目（提交创建成功后选中新项目） */
  onSelectProject: (id: number) => void
}

export function usePatternRoomProjectActions(options: UsePatternRoomProjectActionsOptions) {
  const {
    canManage,
    confirmDialog,
    groupHook,
    projectHook,
    selectedProjectId,
    searchKeyword,
    statusFilter,
    isNarrow,
    drawerOpen,
    formPatternMakerId,
    onSelectProject,
  } = options

  /** 项目表单弹窗可见性 */
  const projectFormVisible = ref(false)
  /** 项目表单模式：新增 / 编辑 */
  const projectFormMode = ref<'create' | 'edit'>('create')
  /** 暂存待上传的项目图片 */
  const pendingProjectImage = ref<File | null>(null)

  function openCreateProjectDialog() {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    projectFormMode.value = 'create'
    formPatternMakerId.value = null
    pendingProjectImage.value = null
    projectFormVisible.value = true
  }

  function openEditProjectDialog() {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (!projectHook.currentProject.value) return
    projectFormMode.value = 'edit'
    formPatternMakerId.value = projectHook.currentProject.value.pattern_maker_id ?? null
    pendingProjectImage.value = null
    projectFormVisible.value = true
  }

  /** 从产品卡片点击「编辑」：加载该产品详情后打开编辑弹窗（支持编辑未选中卡片） */
  async function onEditProjectFromCard(id: number) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    selectedProjectId.value = id
    const detail = await projectHook.fetchDetail(id)
    if (!detail) return
    projectFormMode.value = 'edit'
    formPatternMakerId.value = detail.pattern_maker_id ?? null
    pendingProjectImage.value = null
    projectFormVisible.value = true
    // 关闭窄屏抽屉，保证编辑弹窗可见
    if (isNarrow.value) drawerOpen.value = false
  }

  /** 从产品卡片点击「完成」：确认后标记项目为已完成并刷新分组列表 */
  async function onCompleteProjectFromCard(id: number) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    const ok = await confirmDialog.confirm(
      '确认将该打样项目标记为完成？',
      '标记后项目状态变为「已完成」，仍可继续编辑。',
    )
    if (!ok) return
    try {
      const res = await patternRoomApi.updateProjectStatus(id, 'completed')
      if (res.success) {
        toast.success('已标记为完成')
        await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value)
      } else {
        toast.error(res.message || '标记完成失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 标记完成失败:', e)
      toast.error('标记完成失败')
    }
  }

  /** 从产品卡片点击「取消」：确认后将打样项目移至已取消 */
  async function onCancelProjectFromCard(id: number) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    const ok = await confirmDialog.confirm(
      '确认取消该打样项目？',
      '取消后项目将移至「已取消」TAB，仍可恢复为进行中。',
    )
    if (!ok) return
    try {
      const res = await patternRoomApi.updateProjectStatus(id, 'cancelled')
      if (res.success) {
        toast.success('已取消')
        await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value)
      } else {
        toast.error(res.message || '取消失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 取消项目失败:', e)
      toast.error('取消失败')
    }
  }

  function onProjectUploadImage(file: File) {
    pendingProjectImage.value = file
  }

  async function onProjectSubmitCreate(data: ProjectCreateRequest) {
    const res = await projectHook.create(data)
    if (res && res.id) {
      // 上传暂存图片
      if (pendingProjectImage.value) {
        const upRes = await projectHook.uploadImage(res.id, pendingProjectImage.value)
        if (!upRes) toast.warning('图片上传失败，项目已创建，请稍后在编辑中重新上传')
      }
      projectFormVisible.value = false
      pendingProjectImage.value = null
      // 刷新分组列表并选中新项目（保持当前状态筛选）
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value)
      onSelectProject(res.id)
    } else {
      toast.error(projectHook.error.value || '创建失败')
    }
  }

  async function onProjectSubmitUpdate(data: ProjectUpdateRequest) {
    if (!selectedProjectId.value) return
    const res = await projectHook.update(selectedProjectId.value, data)
    if (res) {
      // 上传暂存图片
      if (pendingProjectImage.value) {
        const upRes = await projectHook.uploadImage(selectedProjectId.value, pendingProjectImage.value)
        if (!upRes) toast.warning('图片上传失败，其他信息已更新')
      }
      toast.success('更新成功')
      projectFormVisible.value = false
      pendingProjectImage.value = null
      // 刷新详情与分组列表（保持当前状态筛选）
      await projectHook.fetchDetail(selectedProjectId.value)
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value)
    } else {
      toast.error(projectHook.error.value || '更新失败')
    }
  }

  /** 删除项目（级联删除部位/版本/日志，带二次确认） */
  async function confirmDeleteProject() {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    if (!projectHook.currentProject.value) return
    const proj = projectHook.currentProject.value
    const ok = await confirmDialog.confirm(
      '确认删除该打样项目？',
      `序列号 ${proj.sequence_no}，此操作将级联删除所有部位、版本与变更日志，且不可恢复。`,
      'danger',
    )
    if (!ok) return
    const res = await projectHook.remove(proj.id)
    if (res) {
      toast.success('删除成功')
      selectedProjectId.value = null
      projectHook.clearCurrent()
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value)
    } else {
      toast.error(projectHook.error.value || '删除失败')
    }
  }

  return {
    projectFormVisible,
    projectFormMode,
    pendingProjectImage,
    openCreateProjectDialog,
    openEditProjectDialog,
    onEditProjectFromCard,
    onCompleteProjectFromCard,
    onCancelProjectFromCard,
    onProjectUploadImage,
    onProjectSubmitCreate,
    onProjectSubmitUpdate,
    confirmDeleteProject,
  }
}
