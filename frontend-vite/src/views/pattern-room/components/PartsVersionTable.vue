<template>
  <div class="pdp-section pdp-parts-section">
    <div v-if="partLoading" class="pdp-loading">
      <UiSpinner size="sm" />
      <span>加载部位数据...</span>
    </div>

    <div v-else-if="partsByVersion.length === 0" class="pdp-empty-parts">
      <i class="fas fa-cubes" aria-hidden="true" />
      <span>暂无部位布料信息</span>
    </div>

    <div v-else class="pdp-parts-table-wrap">
      <table class="pdp-parts-table pdp-parts-table--version">
        <colgroup>
          <col style="width: 100px">
          <col style="width: 60px">
          <col style="width: 110px">
          <col style="width: 110px">
          <col style="width: 110px">
          <col style="width: 110px">
        </colgroup>
        <thead>
          <tr>
            <th class="pdp-part-name-th">部位名称</th>
            <th>版本</th>
            <th>供应商</th>
            <th>布料名称</th>
            <th>色号</th>
            <th class="pdp-actions-th">功能</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in groupedRows" :key="group.part_name">
            <PartVersionRowGroup
              :group="group"
              :editing-part-id="editingPartId"
              :edit-form="editForm"
              :can-manage="canManage"
              :selected-version="selectedVersion"
              @toggle-expand="toggleExpand"
              @toggle-version="toggleVersion"
              @start-edit="startEdit"
              @save-edit="saveEdit"
              @cancel-edit="cancelEdit"
              @copy-version="(part) => emit('copy-version', part)"
              @delete-version="(part) => emit('delete-version', part)"
            />
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSpinner from '@/components/ui/UiSpinner.vue'
import PartVersionRowGroup from './PartVersionRowGroup.vue'
import { useProjectDetail, type ProjectDetailPanelEmit } from '../composables/useProjectDetail'
import type { ProjectDetailResponse, PartDetail } from '@/api/patternRoom'

const props = defineProps<{
  project: ProjectDetailResponse | null
  partsByVersion: PartDetail[]
  finalVersion: string
  partLoading: boolean
  canManage: boolean
  currentRoleId: number | null
}>()

const emit = defineEmits<{
  'set-final-version': [versionNo: string]
  'copy-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
  'save-edit': [part: PartDetail, data: { supplier_name: string; fabric_name: string; fabric_color_no: string }]
}>()

const {
  editingPartId,
  editForm,
  selectedVersion,
  startEdit,
  saveEdit,
  cancelEdit,
  toggleVersion,
  toggleExpand,
  groupedRows,
} = useProjectDetail(props, emit as unknown as ProjectDetailPanelEmit)
</script>

<style scoped>
.pdp-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
}
.pdp-section:last-child {
  border-bottom: none;
}
.pdp-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-secondary, #475569);
  font-size: 13px;
}
.pdp-empty-parts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 13px;
}
.pdp-empty-parts i {
  font-size: 32px;
  opacity: 0.4;
  color: var(--color-text-secondary, #475569);
}
.pdp-parts-section {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.pdp-parts-table-wrap {
  flex: 1;
  overflow: auto;
}
.pdp-parts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}
.pdp-parts-table th,
.pdp-parts-table td {
  padding: 10px 12px;
  text-align: left;
  border: 1px solid #d9dce3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
}
.pdp-parts-table th {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 1;
  font-size: 13px;
  text-align: center;
}
.pdp-parts-table tbody tr:hover {
  background: transparent;
}
.pdp-parts-table--version th {
  text-align: center;
}
.pdp-parts-table--version td {
  text-align: center;
}
.pdp-part-name-th {
  text-align: center !important;
}
</style>