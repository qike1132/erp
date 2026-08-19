<template>
  <div class="pr-container">
    <div class="page-card page-card-main">
      <div class="page-card-header pr-top-bar">
        <button
          v-if="canManage"
          class="pr-add-btn pr-add-btn--primary"
          @click="openCreateProjectDialog"
        >
          新建打样
        </button>
      </div>

      <div class="page-card-body pr-body">
        <UiAlert
          v-if="groupHook.error.value"
          variant="danger"
          title="加载失败"
          closable
          @close="groupHook.error.value = null"
        >
          {{ groupHook.error.value }}
        </UiAlert>

        <PatternRoomSplitBody :is-narrow="isNarrow" v-model:drawer-open="drawerOpen">
          <template #group-list>
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
          </template>
          <template #detail-panel>
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
          </template>
        </PatternRoomSplitBody>
      </div>
    </div>

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

    <PartFormDialog
      :open="partFormVisible"
      :submitting="partHook.submitting.value"
      @update:open="partFormVisible = $event"
      @submit-batch="onPartSubmitBatch"
    />

    <VersionCreateDialog
      :open="versionCreateVisible"
      :current-version="projectHook.currentProject.value?.current_version ?? 'T1'"
      :submitting="versionHook.submitting.value"
      @update:open="versionCreateVisible = $event"
      @confirm="onVersionCreateConfirm"
    />

    <PrintDialog
      ref="printDialogRef"
      :project="projectHook.currentProject.value"
      :parts="printParts"
      :roles="printRoles"
    />

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
import { ref, computed, watch, onMounted } from 'vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import CustomerGroupList from './components/CustomerGroupList.vue'
import ProjectDetailPanel from './components/ProjectDetailPanel.vue'
import ProjectFormDialog from './components/ProjectFormDialog.vue'
import PartFormDialog from './components/PartFormDialog.vue'
import VersionCreateDialog from './components/VersionCreateDialog.vue'
import PrintDialog from './components/PrintDialog.vue'
import PatternRoomSplitBody from './components/PatternRoomSplitBody.vue'

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

const { hasPermission } = usePermission()
const canManage = computed(() => hasPermission('customer_sampling_manage'))

const groupHook = useCustomerSampling()
const projectHook = useSamplingProject()

const selectedProjectId = ref<number | null>(null)
const roleHook = useSamplingRole(selectedProjectId)
const partHook = useSamplingPart(selectedProjectId, roleHook.currentRoleId)
const versionHook = useSamplingVersion(selectedProjectId, roleHook.currentRoleId)

const {
  statusFilter,
  searchKeyword,
  onStatusChange,
  onGroupPageChange,
  onSearch,
} = usePatternRoomGroupFilter(groupHook)

const confirmDialog = useConfirmDialog()

const {
  patternMakers,
  formPatternMakerId,
  loadPatternMakers,
  handleAddPatternMaker,
  handleDeletePatternMaker,
} = usePatternRoomPatternMakers(canManage, confirmDialog)

const { isNarrow, drawerOpen } = usePatternRoomLayout()

onMounted(() => {
  groupHook.loadGrouped(searchKeyword.value || undefined, 'in_progress', 1)
  loadPatternMakers()
})

function onSelectProject(id: number) {
  selectedProjectId.value = id
  projectHook.fetchDetail(id)
  if (isNarrow.value) drawerOpen.value = false
}

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

watch(selectedProjectId, (newId) => {
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
</style>
