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
      <!-- 顶部：HeaderTabs + 操作按钮 -->
      <div class="page-card-header pr-top-bar">
        <div class="pr-top-left"><HeaderTabs /></div>
        <div class="pr-top-right">
          <button
            v-if="canManage"
            class="pr-add-btn pr-add-btn--primary"
            @click="openCreateProjectDialog"
          >
            <i class="fas fa-plus" aria-hidden="true" />
            新增打样项目
          </button>
          <button
            v-if="canManage && selectedProjectId"
            class="pr-add-btn"
            @click="openCreatePartDialog"
          >
            <i class="fas fa-plus" aria-hidden="true" />
            录入布料信息
          </button>
        </div>
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
          <aside v-if="!isNarrow" class="pr-left-pane" :class="{ 'pr-left-collapsed': leftCollapsed }">
            <button class="pr-collapse-btn" :aria-label="leftCollapsed ? '展开' : '折叠'" @click="leftCollapsed = !leftCollapsed">
              <i :class="['fas', leftCollapsed ? 'fa-chevron-right' : 'fa-chevron-left']" aria-hidden="true" />
            </button>
            <div v-show="!leftCollapsed" class="pr-left-content">
              <CustomerGroupList
                :groups="groupHook.groups.value"
                :loading="groupHook.loading.value"
                :has-data="groupHook.hasData.value"
                :selected-project-id="selectedProjectId"
                @select-project="onSelectProject"
                @search="onSearch"
                @add-project="openCreateProjectDialog"
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
              :version-loading="versionHook.loading.value"
              :part-loading="partHook.loading.value"
              :can-manage="canManage"
              @copy-version="onCopyPartVersion"
              @delete-version="onDeleteVersion"
              @save-edit="onSaveEdit"
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
        @select-project="onSelectProjectFromDrawer"
        @search="onSearch"
        @add-project="openCreateProjectDialog"
      />
    </UiDrawer>

    <!-- 项目表单弹窗（新增/编辑） -->
    <ProjectFormDialog
      :visible="projectFormVisible"
      :project="projectFormMode === 'edit' ? projectHook.currentProject.value : null"
      :customers="customers"
      :submitting="projectHook.submitting.value"
      @update:visible="projectFormVisible = $event"
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
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import CustomerGroupList from './components/CustomerGroupList.vue'
import ProjectDetailPanel from './components/ProjectDetailPanel.vue'
import ProjectFormDialog from './components/ProjectFormDialog.vue'
import PartFormDialog from './components/PartFormDialog.vue'
import VersionCreateDialog from './components/VersionCreateDialog.vue'

import { useCustomerSampling } from './composables/useCustomerSampling'
import { useSamplingProject } from './composables/useSamplingProject'
import { useSamplingPart } from './composables/useSamplingPart'
import { useSamplingVersion } from './composables/useSamplingVersion'

import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePermission } from '@/composables/usePermission'
import { toast } from '@/composables/useToast'

import { customerApi } from '@/api/customer'
import type { Customer } from '@/types'
import type {
  ProjectCreateRequest,
  ProjectUpdateRequest,
  BatchPartCreateRequest,
  PartDetail,
  PartUpdateRequest,
} from '@/api/patternRoom'
import { patternRoomApi } from '@/api/patternRoom'

// ==================== 权限 ====================
const { hasPermission } = usePermission()
const canManage = computed(() => hasPermission('customer_sampling_manage'))

// ==================== Hooks ====================
const groupHook = useCustomerSampling()
const projectHook = useSamplingProject()

/** 当前选中项目 ID（响应式，传给 Part/Version Hook 自动 watch） */
const selectedProjectId = ref<number | null>(null)
const partHook = useSamplingPart(selectedProjectId)
const versionHook = useSamplingVersion(selectedProjectId)

// ==================== 客户列表（项目表单选项） ====================
const customers = ref<Customer[]>([])

async function loadCustomers() {
  try {
    const res = await customerApi.list({ per_page: 200 })
    customers.value = res.customers ?? []
  } catch (e) {
    console.error('[PatternRoomView] 加载客户列表失败:', e)
  }
}

// ==================== 响应式布局 ====================
const isNarrow = ref(false)
const leftCollapsed = ref(false)
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
  // 初始化加载
  groupHook.loadGrouped()
  loadCustomers()
})

onUnmounted(() => {
  _mediaQuery?.removeEventListener('change', updateNarrow)
})

// ==================== 搜索（防抖） ====================
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearch(keyword: string) {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    groupHook.loadGrouped(keyword || undefined)
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
  pendingProjectImage.value = null
  projectFormVisible.value = true
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
    toast.success(`创建成功，序列号 ${res.sequence_no ?? ''}`)
    projectFormVisible.value = false
    pendingProjectImage.value = null
    // 刷新分组列表并选中新项目
    await groupHook.loadGrouped()
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
    // 刷新详情与分组列表
    await projectHook.fetchDetail(selectedProjectId.value)
    await groupHook.loadGrouped()
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
    await groupHook.loadGrouped()
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
    const res = await patternRoomApi.batchCreateParts(selectedProjectId.value, data)
    if (res.success) {
      toast.success(res.message || `已创建 ${data.items.length} 个部位`)
      partFormVisible.value = false
      if (selectedProjectId.value) {
        await projectHook.fetchDetail(selectedProjectId.value)
        await partHook.fetchPartsByVersion(selectedProjectId.value)
      }
    } else {
      toast.error(res.message || '批量创建失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 批量创建部位失败:', e)
    toast.error('批量创建部位失败')
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
        await partHook.fetchPartsByVersion(selectedProjectId.value)
      }
    } else {
      toast.error(res.message || '复制版本失败')
    }
  } catch (e) {
    console.error('[PatternRoomView] 复制部位版本失败:', e)
    toast.error('复制部位版本失败')
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
        await partHook.fetchPartsByVersion(selectedProjectId.value)
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
  const ok = await confirmDialog.confirm(
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
        await partHook.fetchPartsByVersion(selectedProjectId.value)
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
    // 刷新项目详情（current_version 更新）
    if (selectedProjectId.value) await projectHook.fetchDetail(selectedProjectId.value)
    // 空快照提示
    if (partHook.parts.value.length === 0) {
      toast.warning('当前无部位布料信息，已创建空版本，建议先维护部位布料')
    }
  } else {
    toast.error(versionHook.error.value || '创建新版本失败')
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

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.pr-top-bar {
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.pr-top-left {
  flex: 1 1 auto;
  min-width: 0;
}

.pr-top-right {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
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

.pr-left-collapsed {
  flex: 0 0 36px;
}

.pr-left-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pr-collapse-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 2;
  width: 24px;
  height: 24px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 6px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
}

.pr-collapse-btn:hover {
  border-color: #ff9f43;
  color: #ff9f43;
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
