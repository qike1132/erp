<template>
  <!--
    PatternRoomView.vue — 按客户分类打样信息模块主容器
    路由: /pattern-room（保持路径不变，用户无感切换）

    布局：左右分栏
      - 左侧（380px，可折叠）：客户分组列表（手风琴 + 打样项目卡片）
      - 右侧（flex:1）：打样详情面板（部位布料 + 版本切换 + 变更记录）

    响应式：窄屏（< 1024px）时左侧改为 UiDrawer 抽屉。

    集成 Hooks：useCustomerSampling / useSamplingProject / useSamplingPart / useSamplingVersion
    CRUD 交互：新增/编辑/删除项目、部位增删改、版本创建、图片上传。

    对应 spec 5.1-5.5 与 design.md 2.4.2。
  -->
  <div class="pr-container">
    <div class="page-card page-card-main">
      <!-- 顶部：操作按钮 -->
      <div class="page-card-header pr-top-bar">
        <!-- 默认按钮：新建打样 -->
        <button
          v-if="canManage"
          class="pr-add-btn pr-add-btn--primary"
          @click="openCreateProjectDialog"
        >
          新建打样
        </button>
      </div>

      <!-- 主体：左右分栏 -->
      <div class="page-card-body pr-body">
        <!-- 加载错误提示 -->
        <UiAlert
          v-if="groupHook.error.value"
          variant="danger"
          title="加载失败"
          closable
          @close="groupHook.error.value = null"
        >
          {{ groupHook.error.value }}
        </UiAlert>

        <!-- 桌面端：左侧固定 + 右侧 flex -->
        <div class="pr-split-layout">
          <!-- 左侧：客户分组列表 -->
          <aside v-if="!isNarrow" class="pr-left-pane">
            <div class="pr-left-content">
              <CustomerGroupList
                :groups="groupHook.groups.value"
                :loading="groupHook.loading.value"
                :has-data="groupHook.hasData.value"
                :selected-project-id="selectedProjectId"
                :can-manage="canManage"
                :group-page="groupHook.currentPage.value"
                :group-pages="groupHook.pages.value"
                :group-total="groupHook.total.value"
                @select-project="onSelectProject"
                @edit-project="onEditProjectFromCard"
                @complete-project="onCompleteProjectFromCard"
                @cancel-project="onCancelProjectFromCard"
                @search="onSearch"
                @add-project="openCreateProjectDialog"
                @status-change="onStatusChange"
                @update-group-page="onGroupPageChange"
              />
            </div>
          </aside>

          <!-- 窄屏：左侧抽屉触发按钮 -->
          <button v-if="isNarrow" class="pr-drawer-trigger" aria-label="打开分组列表" @click="drawerOpen = true">
            <i class="fas fa-bars" aria-hidden="true" />
          </button>

          <!-- 右侧：打样详情面板 -->
          <main class="pr-right-pane">
            <ProjectDetailPanel
              :project="projectHook.currentProject.value"
              :parts-by-version="partHook.partsByVersion.value"
              :version-list="partHook.versionList.value"
              :final-version="partHook.finalVersion.value"
              :version-loading="versionHook.loading.value"
              :part-loading="partHook.loading.value"
              :can-manage="canManage"
              :can-print="canPrint"
              :roles="roleHook.roles.value"
              :current-role-id="roleHook.currentRoleId.value"
              @set-final-version="onSetFinalVersion"
              @copy-version="onCopyPartVersion"
              @delete-version="onDeleteVersion"
              @save-edit="onSaveEdit"
              @select-role="onSelectRole"
              @add-role="onAddRole"
              @remove-role="onRemoveRole"
              @add-part="openCreatePartDialog"
              @print="handlePrint"
            />
          </main>
        </div>
      </div>
    </div>

    <!-- 窄屏抽屉：客户分组列表 -->
    <UiDrawer
      v-if="isNarrow"
      :visible="drawerOpen"
      position="left"
      title="打样项目列表"
      width="320px"
      @update:visible="drawerOpen = $event"
    >
      <CustomerGroupList
        :groups="groupHook.groups.value"
        :loading="groupHook.loading.value"
        :has-data="groupHook.hasData.value"
        :selected-project-id="selectedProjectId"
        :can-manage="canManage"
        :group-page="groupHook.currentPage.value"
        :group-pages="groupHook.pages.value"
        :group-total="groupHook.total.value"
        @select-project="onSelectProjectFromDrawer"
        @edit-project="onEditProjectFromCard"
        @complete-project="onCompleteProjectFromCard"
        @search="onSearch"
        @add-project="openCreateProjectDialog"
        @status-change="onStatusChange"
        @update-group-page="onGroupPageChange"
      />
    </UiDrawer>

    <!-- 项目表单弹窗（新增/编辑） -->
    <ProjectFormDialog
      :visible="projectFormVisible"
      :project="projectFormMode === 'edit' ? projectHook.currentProject.value : null"
      :pattern-makers="patternMakers"
      :pattern-maker-id="formPatternMakerId"
      :submitting="projectHook.submitting.value"
      @update:visible="projectFormVisible = $event"
      @update:pattern-maker-id="formPatternMakerId = $event"
      @add-pattern-maker="handleAddPatternMaker"
      @delete-pattern-maker="handleDeletePatternMaker"
      @submit-create="onProjectSubmitCreate"
      @submit-update="onProjectSubmitUpdate"
      @upload-image="onProjectUploadImage"
      @remove-image="pendingProjectImage = null"
    />

    <!-- 部位表单弹窗（新增/编辑） -->
    <PartFormDialog
      :open="partFormVisible"
      :submitting="partHook.submitting.value"
      @update:open="partFormVisible = $event"
      @submit-batch="onPartSubmitBatch"
    />

    <!-- 版本创建弹窗 -->
    <VersionCreateDialog
      :open="versionCreateVisible"
      :current-version="projectHook.currentProject.value?.current_version ?? 'T1'"
      :submitting="versionHook.submitting.value"
      @update:open="versionCreateVisible = $event"
      @confirm="onVersionCreateConfirm"
    />

    <!-- 打印打样单内容（屏幕上隐藏，打印时仅显示） -->
    <PrintDialog
      ref="printDialogRef"
      :project="projectHook.currentProject.value"
      :parts="printParts"
      :roles="printRoles"
    />


    <!-- 删除确认对话框 -->
    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @update:open="confirmDialog.open = $event"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * PatternRoomView — 按客户分类打样信息模块主容器
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import CustomerGroupList from './components/CustomerGroupList.vue'
import ProjectDetailPanel from './components/ProjectDetailPanel.vue'
import ProjectFormDialog from './components/ProjectFormDialog.vue'
import PartFormDialog from './components/PartFormDialog.vue'
import VersionCreateDialog from './components/VersionCreateDialog.vue'
import PrintDialog from './components/PrintDialog.vue'

import { useCustomerSampling } from './composables/useCustomerSampling'
import { useSamplingProject } from './composables/useSamplingProject'
import { useSamplingPart } from './composables/useSamplingPart'
import { useSamplingVersion } from './composables/useSamplingVersion'
import { useSamplingRole } from './composables/useSamplingRole'

import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePermission } from '@/composables/usePermission'
import { toast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

import type {
  ProjectCreateRequest,
  ProjectUpdateRequest,
  BatchPartCreateRequest,
  PartDetail,
  PartUpdateRequest,
  RoleBrief,
} from '@/api/patternRoom'
import { patternRoomApi } from '@/api/patternRoom'
import { patternMakerApi } from '@/api/patternMaker'
import type { PatternMaker } from '@/api/patternMaker'

// ==================== 权限 ====================
const { hasPermission } = usePermission()
const canManage = computed(() => hasPermission('customer_sampling_manage'))

// ==================== 状态筛选 ====================
/** 状态筛选：in_progress/completed/cancelled */
const statusFilter = ref<string>('in_progress')
/** 搜索关键词 */
const searchKeyword = ref('')

function onStatusChange(val: string) {
  statusFilter.value = val
  // 所有状态现在都用分组卡片视图 + 分页，所以直接加载
  groupHook.loadGrouped(searchKeyword.value || undefined, val, 1)
}

/** 分组视图翻页 */
function onGroupPageChange(page: number) {
  if (page === groupHook.currentPage.value) return
  groupHook.loadGrouped(searchKeyword.value || undefined, statusFilter.value, page)
}

// ==================== 打印打样单 ====================
/** 打印内容组件引用（用于打印前刷新打印时间） */
const printDialogRef = ref<{ updatePrintTime: () => void } | null>(null)
/** 打印用部位数据（全部角色，点击打印时才加载） */
const printParts = ref<PartDetail[]>([])
/** 打印用角色分组（role_id → role_name 映射） */
const printRoles = ref<RoleBrief[]>([])
/** 可打印：已选中产品且有部位数据 */
const canPrint = computed(
  () => selectedProjectId.value != null && partHook.partsByVersion.value.length > 0,
)

async function handlePrint() {
  if (!canPrint.value || !selectedProjectId.value) return
  const projectId = selectedProjectId.value
  const roles = roleHook.roles.value
  printRoles.value = roles
  // 后端不支持不传 role_id 返回全部角色，需逐个角色加载
  try {
    const allParts: PartDetail[] = []
    for (const role of roles) {
      const res = await patternRoomApi.getPartsByVersion(projectId, role.id)
      const items = res.items ?? []
      // 确保每条数据带 role_id（用于 PrintDialog 按角色分组）
      for (const item of items) {
        if (item.role_id == null) item.role_id = role.id
        allParts.push(item)
      }
    }
    printParts.value = allParts
  } catch {
    // 降级：使用当前角色的数据
    printParts.value = partHook.partsByVersion.value
  }
  // 打印前刷新打印时间
  printDialogRef.value?.updatePrintTime()
  // 给 body 加打印隔离类，仅显示打样单内容
  document.body.classList.remove('pd-printing')
  document.body.classList.add('pd-printing')
  // 临时清空页面标题，避免浏览器打印预览页眉显示"滨发协同系统"
  const prevTitle = document.title
  document.title = ''
  // 等待打印内容渲染后，直接调出浏览器打印预览
  requestAnimationFrame(() => {
    window.print()
  })
}

if (typeof window !== 'undefined') {
  window.addEventListener('afterprint', () => {
    document.body.classList.remove('pd-printing')
    // 恢复页面标题
    document.title = '滨发协同系统'
  })
}

// ==================== Hooks ====================
const groupHook = useCustomerSampling()
const projectHook = useSamplingProject()

/** 当前选中项目 ID（响应式，传给 Role/Part/Version Hook 自动 watch） */
const selectedProjectId = ref<number | null>(null)
/** 角色管理 hook（先于 part/version 初始化，提供 currentRoleId） */
const roleHook = useSamplingRole(selectedProjectId)
const partHook = useSamplingPart(selectedProjectId, roleHook.currentRoleId)
const versionHook = useSamplingVersion(selectedProjectId, roleHook.currentRoleId)

// ==================== 版师列表（项目表单选项） ====================
const patternMakers = ref<PatternMaker[]>([])
/** 弹窗当前选中的版师 ID（v-model 双向绑定） */
const formPatternMakerId = ref<number | null>(null)

async function loadPatternMakers() {
  try {
    const res = await patternMakerApi.list()
    patternMakers.value = res.items ?? []
  } catch (e) {
    console.error('[PatternRoomView] 加载版师列表失败:', e)
  }
}

/** 新增版师：调用接口、刷新列表并选中新增项 */
async function handleAddPatternMaker(name: string) {
  if (!canManage.value) {
    toast.warning('无操作权限')
    return
  }
  try {
    const res = await patternMakerApi.create({ name })
    if (res.success) {
      await loadPatternMakers()
      if (res.id != null) {
        formPatternMakerId.value = res.id
      }
      toast.success('版师添加成功')
    } else {
      toast.error(res.message || '版师添加失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 新增版师失败:', e)
    toast.error('版师添加失败')
  }
}

/** 删除版师：调用接口、刷新列表，若删除的是当前选中项则清空选择 */
async function handleDeletePatternMaker(id: number) {
  if (!canManage.value) {
    toast.warning('无操作权限')
    return
  }
  const ok = await confirmDialog.confirm(
    '确认删除该版师？',
    '关联的打样项目将变为「未分类」，不会删除项目数据。',
    'danger',
  )
  if (!ok) return
  try {
    const res = await patternMakerApi.delete(id)
    if (res.success) {
      if (formPatternMakerId.value === id) {
        formPatternMakerId.value = null
      }
      await loadPatternMakers()
      toast.success('版师删除成功')
    } else {
      toast.error(res.message || '版师删除失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 删除版师失败:', e)
    toast.error('版师删除失败')
  }
}

// ==================== 响应式布局 ====================
const isNarrow = ref(false)
const drawerOpen = ref(false)

let _mediaQuery: MediaQueryList | null = null
function updateNarrow() {
  isNarrow.value = _mediaQuery?.matches ?? false
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    _mediaQuery = window.matchMedia('(max-width: 1023px)')
    updateNarrow()
    _mediaQuery.addEventListener('change', updateNarrow)
  }
  // 初始化加载（默认「进行中」，第 1 页）
  groupHook.loadGrouped(searchKeyword.value || undefined, 'in_progress', 1)
  loadPatternMakers()
})

onUnmounted(() => {
  _mediaQuery?.removeEventListener('change', updateNarrow)
})

// ==================== 搜索（防抖） ====================
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearch(keyword: string) {
  searchKeyword.value = keyword
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    groupHook.loadGrouped(keyword || undefined, statusFilter.value, 1)
  }, 300)
}

// ==================== 选中项目 ====================
function onSelectProject(id: number) {
  selectedProjectId.value = id
  projectHook.fetchDetail(id)
  // Part/Version Hook 会自动 watch selectedProjectId 加载数据
  if (isNarrow.value) drawerOpen.value = false
}

function onSelectProjectFromDrawer(id: number) {
  onSelectProject(id)
}

// ==================== 版本切换 ====================
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

// ==================== 项目 CRUD ====================
const projectFormVisible = ref(false)
const projectFormMode = ref<'create' | 'edit'>('create')
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

// ==================== 删除项目 ====================
const confirmDialog = useConfirmDialog()

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

// ==================== 部位批量创建 ====================
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
        await projectHook.fetchDetail(selectedProjectId.value)
        await partHook.fetchPartsByVersion(
          selectedProjectId.value,
          roleHook.currentRoleId.value ?? undefined,
        )
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
      if (selectedProjectId.value) {
        await partHook.fetchPartsByVersion(
          selectedProjectId.value,
          roleHook.currentRoleId.value ?? undefined,
        )
      }
    } else {
      toast.error(res.message || '保存失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 保存部位编辑失败:', e)
    const errMsg = (e as { response?: { status?: number } })?.response?.status === 409
      ? '数据已被他人更新，请刷新后重试'
      : '保存失败'
    toast.error(errMsg)
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
      if (selectedProjectId.value) {
        await partHook.fetchPartsByVersion(
          selectedProjectId.value,
          roleHook.currentRoleId.value ?? undefined,
        )
      }
    } else {
      toast.error(res.message || '删除失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 删除部位版本失败:', e)
    toast.error('删除部位版本失败')
  }
}

// ==================== 版本创建 ====================
const versionCreateVisible = ref(false)

function openCreateVersionDialog() {
  if (!canManage.value) {
    toast.warning('无操作权限')
    return
  }
  versionCreateVisible.value = true
}

async function onVersionCreateConfirm(reason: string | null) {
  const res = await versionHook.createVersion(reason ?? undefined)
  if (res) {
    toast.success(res.message || `已创建版本 ${res.version_no ?? ''}`)
    versionCreateVisible.value = false
    // 刷新角色列表（current_version 更新）+ 项目详情
    if (selectedProjectId.value) {
      await roleHook.fetchRoles(selectedProjectId.value)
      await projectHook.fetchDetail(selectedProjectId.value)
    }
    // 空快照提示
    if (partHook.parts.value.length === 0) {
      toast.warning('当前无部位布料信息，已创建空版本，建议先维护部位布料')
    }
  } else {
    toast.error(versionHook.error.value || '创建新版本失败')
  }
}

// ==================== 角色 TAB 切换/增删 ====================
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

async function onRemoveRole(role: { id: number; role_name: string; is_default: boolean }) {
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

// ==================== watch 选中项目变化时刷新详情 ====================
// 注意：useSamplingPart/useSamplingVersion 已内部 watch selectedProjectId
// 这里只需 watch 刷新项目详情（projectHook.fetchDetail 已在 onSelectProject 调用）
// 但为兜底（如外部直接修改 selectedProjectId），增加 watch
watch(selectedProjectId, (newId, oldId) => {
  if (newId !== oldId && newId != null) {
    // onSelectProject 已调用 fetchDetail，此处避免重复
    // 仅处理清空场景
  }
  if (newId == null) {
    projectHook.clearCurrent()
  }
})
</script>

<style scoped>
.pr-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
}

.pr-top-bar {
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.pr-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7280);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  white-space: nowrap;
  font-family: inherit;
}

.pr-add-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.pr-add-btn--primary {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.pr-add-btn--primary:hover {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

.pr-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  padding: 12px;
  gap: 8px;
}

.pr-split-layout {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左侧 */
.pr-left-pane {
  position: relative;
  flex: 0 0 680px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
  transition: flex-basis 0.25s ease;
  display: flex;
  flex-direction: column;
}

.pr-left-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 窄屏抽屉触发 */
.pr-drawer-trigger {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 10px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: all 0.2s ease;
}

.pr-drawer-trigger:hover {
  border-color: #ff9f43;
  color: #ff9f43;
}

/* 右侧 */
.pr-right-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 窄屏布局 */
@media (max-width: 1023px) {
  .pr-split-layout {
    flex-direction: column;
  }
  .pr-right-pane {
    flex: 1;
  }
}
</style>
