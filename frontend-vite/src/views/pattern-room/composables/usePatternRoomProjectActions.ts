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
        // 静默刷新分组列表：状态变更是增量更新，不能用 loading 全面板交换
        // （v-if 摘除重挂载会丢失虚拟列表滚动位置与组内分页状态，视觉上等同整页刷新）
        await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true, true)
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
        // 静默刷新分组列表：同完成操作，避免 loading 全面板交换丢失页面状态与滚动位置
        await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true, true)
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

  /**
   * 后台上传暂存图片（不阻塞保存成功的即时反馈）
   *
   * 成功：用上传接口返回的 URL 本地打补丁（详情图片即时显示，无需二次请求），
   * 并刷新分组列表让卡片缩略图更新；失败：仅提示，不打扰主流程。
   */
  function uploadPendingImage(projectId: number, image: File, failMessage: string) {
    void patternRoomApi.uploadProjectImage(projectId, image)
      .then((upRes) => {
        if (upRes?.success) {
          // 本地打补丁：详情图片即时显示（上传接口已返回 URL/缩略图 URL）
          const proj = projectHook.currentProject.value
          if (proj && proj.id === projectId) {
            if (upRes.url) proj.product_image_url = upRes.url
            if (upRes.thumbnail_url) proj.product_image_thumbnail_url = upRes.thumbnail_url
            if (upRes.file_id != null) proj.product_image_file_id = upRes.file_id
          }
          // 刷新分组列表，让卡片缩略图显示新图片
          void groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true)
        } else {
          toast.warning(failMessage)
        }
      })
      .catch(() => {
        toast.warning(failMessage)
      })
  }

  async function onProjectSubmitCreate(data: ProjectCreateRequest) {
    const res = await projectHook.create(data)
    if (res && res.id) {
      const newProjectId = res.id
      const pendingImage = pendingProjectImage.value
      // 创建成功：立即反馈并关闭弹窗，图片改为后台异步上传，避免用户等待上传完成
      toast.success('创建成功')
      projectFormVisible.value = false
      pendingProjectImage.value = null
      // 刷新分组列表并选中新项目（保持当前状态筛选）
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true)
      onSelectProject(newProjectId)
      // 后台上传暂存图片（不阻塞成功反馈）
      if (pendingImage) {
        uploadPendingImage(newProjectId, pendingImage, '图片上传失败，项目已创建，请稍后在编辑中重新上传')
      }
    } else {
      toast.error(projectHook.error.value || '创建失败')
    }
  }

  async function onProjectSubmitUpdate(data: ProjectUpdateRequest) {
    if (!selectedProjectId.value) return
    const projectId = selectedProjectId.value
    const res = await projectHook.update(projectId, data)
    if (res) {
      const pendingImage = pendingProjectImage.value
      // 更新成功：立即反馈并关闭弹窗，图片改为后台异步上传，避免用户等待上传完成
      toast.success('更新成功')
      projectFormVisible.value = false
      pendingProjectImage.value = null
      // 刷新详情与分组列表（保持当前状态筛选）
      await projectHook.fetchDetail(projectId)
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true)
      // 后台上传暂存图片（不阻塞成功反馈）
      if (pendingImage) {
        uploadPendingImage(projectId, pendingImage, '图片上传失败，其他信息已更新')
      }
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
      await groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, groupHook.currentPage.value, true)
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
