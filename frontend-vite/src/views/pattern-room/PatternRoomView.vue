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
 *
 * 拆分后职责：壳层编排（布局/搜索/选中/初始化），业务动作下沉至 composables：
 *  - 打印打样单 → usePatternRoomPrint
 *  - 版师列表 → usePatternRoomPatternMakers
 *  - 项目 CRUD 弹窗 → usePatternRoomProjectActions
 *  - 部位/版本/角色操作 → usePatternRoomPartActions
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

import { usePatternRoomPrint } from './composables/usePatternRoomPrint'
import { usePatternRoomPatternMakers } from './composables/usePatternRoomPatternMakers'
import { usePatternRoomProjectActions } from './composables/usePatternRoomProjectActions'
import { usePatternRoomPartActions } from './composables/usePatternRoomPartActions'
import { usePatternRoomLayout } from './composables/usePatternRoomLayout'
import { usePatternRoomGroupFilter } from './composables/usePatternRoomGroupFilter'

import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePermission } from '@/composables/usePermission'

// ==================== 权限 ====================
const { hasPermission } = usePermission()
const canManage = computed(() => hasPermission('customer_sampling_manage'))

// ==================== Hooks ====================
const groupHook = useCustomerSampling()
const projectHook = useSamplingProject()

/** 当前选中项目 ID（响应式，传给 Role/Part/Version Hook 自动 watch） */
const selectedProjectId = ref<number | null>(null)
/** 角色管理 hook（先于 part/version 初始化，提供 currentRoleId） */
const roleHook = useSamplingRole(selectedProjectId)
const partHook = useSamplingPart(selectedProjectId, roleHook.currentRoleId)
const versionHook = useSamplingVersion(selectedProjectId, roleHook.currentRoleId)

// ==================== 状态筛选 / 搜索 / 翻页 ====================
const {
  statusFilter,
  searchKeyword,
  onStatusChange,
  onGroupPageChange,
  onSearch,
} = usePatternRoomGroupFilter(groupHook)

// ==================== 确认弹窗（全模块共享同一实例） ====================
const confirmDialog = useConfirmDialog()

// ==================== 版师列表（项目表单选项） ====================
const {
  patternMakers,
  formPatternMakerId,
  loadPatternMakers,
  handleAddPatternMaker,
  handleDeletePatternMaker,
} = usePatternRoomPatternMakers(canManage, confirmDialog)

// ==================== 响应式布局 ====================
const { isNarrow, drawerOpen } = usePatternRoomLayout()

// ==================== 初始化加载（默认「进行中」，第 1 页） ====================
onMounted(() => {
  groupHook.loadGrouped(searchKeyword.value || undefined, 'in_progress', 1)
  loadPatternMakers()
})

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

// ==================== 打印打样单 ====================
const {
  printDialogRef,
  printParts,
  printRoles,
  canPrint,
  handlePrint,
} = usePatternRoomPrint({
  selectedProjectId,
  partsByVersion: partHook.partsByVersion,
  roles: roleHook.roles,
})

// ==================== 项目 CRUD ====================
const {
  projectFormVisible,
  projectFormMode,
  pendingProjectImage,
  openCreateProjectDialog,
  onEditProjectFromCard,
  onCompleteProjectFromCard,
  onCancelProjectFromCard,
  onProjectUploadImage,
  onProjectSubmitCreate,
  onProjectSubmitUpdate,
} = usePatternRoomProjectActions({
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
})

// ==================== 部位批量创建 / 版本 / 角色 ====================
const {
  partFormVisible,
  versionCreateVisible,
  openCreatePartDialog,
  onPartSubmitBatch,
  onSetFinalVersion,
  onCopyPartVersion,
  onSaveEdit,
  onDeleteVersion,
  onVersionCreateConfirm,
  onSelectRole,
  onAddRole,
  onRemoveRole,
} = usePatternRoomPartActions({
  canManage,
  confirmDialog,
  selectedProjectId,
  projectHook,
  partHook,
  versionHook,
  roleHook,
})

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
