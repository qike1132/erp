<template>
  <div class="pdp-container">
    <EmptyState
      v-if="!project"
      icon="hand-point-left"
      title="请选择一个打样项目"
      description="从左侧列表中选择项目查看详情"
    />

    <template v-else>
      <RoleTabs
        :roles="roles"
        :current-role-id="currentRoleId"
        :can-manage="canManage"
        @select="$emit('select-role', $event)"
        @add="$emit('add-role', $event)"
        @remove="$emit('remove-role', $event)"
      >
        <template #actions>
          <button
            v-if="canManage"
            type="button"
            class="pdp-head-btn"
            title="基于当前部位布料信息快照创建新版本"
            @click="$emit('create-version')"
          >
            <FontAwesomeIcon icon="layer-group" aria-hidden="true" />
            创建新版本
          </button>
          <button
            v-if="canManage"
            type="button"
            class="pdp-head-btn"
            @click="$emit('add-part')"
          >
            录入信息
          </button>
          <button
            type="button"
            class="pdp-head-btn"
            :disabled="!canPrint"
            :title="!canPrint ? '当前产品暂无部位数据，无法打印' : '打印该产品全部部位明细'"
            @click="$emit('print')"
          >
            <FontAwesomeIcon icon="print" aria-hidden="true" />
            打印打样单
          </button>
        </template>
      </RoleTabs>

      <PartsVersionTableV2
        :parts-by-version="partsByVersion"
        :final-version="finalVersion"
        :project-id="project?.id"
        :current-role-id="currentRoleId"
        :part-loading="partLoading"
        :can-manage="canManage"
        :editing-part-id="editingPartId"
        :edit-form="editForm"
        @set-final-version="$emit('set-final-version', $event)"
        @copy-version="$emit('copy-version', $event)"
        @delete-version="$emit('delete-version', $event)"
        @start-edit="$emit('start-edit', $event)"
        @cancel-edit="$emit('cancel-edit')"
        @save-edit="$emit('save-edit', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import EmptyState from './EmptyState.vue'
import RoleTabs from './RoleTabs.vue'
import PartsVersionTableV2 from './PartsVersionTableV2.vue'
import type { ProjectDetailResponse, PartDetail, RoleBrief } from '@/api/patternRoom'
import type { PartEditData } from '../composables/usePartInlineEdit'

defineProps<{
  project: ProjectDetailResponse | null
  partsByVersion: PartDetail[]
  finalVersion: string
  partLoading: boolean
  canManage: boolean
  canPrint: boolean
  roles: RoleBrief[]
  currentRoleId: number | null
  editingPartId: number | undefined
  editForm: PartEditData
}>()

defineEmits<{
  'set-final-version': [versionNo: string]
  'copy-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
  'start-edit': [part: PartDetail]
  'cancel-edit': []
  'save-edit': [part: PartDetail]
  'select-role': [roleId: number]
  'add-role': [roleName: string]
  'remove-role': [role: RoleBrief]
  'add-part': []
  'create-version': []
  'print': []
}>()
</script>

<style scoped>
.pdp-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 12px;
  background: #fff;
}

.pdp-head-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  font-size: 12px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}

.pdp-head-btn:hover:not(:disabled) {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.pdp-head-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
