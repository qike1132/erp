<template>
  <div class="pvt-section">
    <div v-if="partLoading" class="pvt-loading">
      <UiSpinner size="sm" />
      <span>加载部位数据...</span>
    </div>

    <div v-else-if="partsByVersion.length === 0" class="pvt-empty-parts">
      <FontAwesomeIcon icon="cubes" aria-hidden="true" />
      <span>暂无部位布料信息</span>
    </div>

    <div v-else class="pvt-table-wrap">
      <table class="pvt-table pvt-table--version">
        <colgroup>
          <col style="width: 100px" />
          <col style="width: 60px" />
          <col style="width: 110px" />
          <col style="width: 110px" />
          <col style="width: 110px" />
          <col style="width: 110px" />
        </colgroup>
        <thead>
          <tr>
            <th class="pvt-part-name-th">部位名称</th>
            <th>版本</th>
            <th>供应商</th>
            <th>布料名称</th>
            <th>色号</th>
            <th class="pvt-actions-th">功能</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in groupedRows" :key="group.part_name">
            <PartsVersionRowV2
              :group="group"
              :editing-part-id="editingPartId"
              :edit-form="editForm"
              :can-manage="canManage"
              :selected-version="selectedVersion"
              :final-version="finalVersion"
              @toggle-expand="toggleExpand"
              @toggle-version="toggleVersion"
              @set-final-version="$emit('set-final-version', $event)"
              @start-edit="$emit('start-edit', $event)"
              @save-edit="$emit('save-edit', $event)"
              @cancel-edit="$emit('cancel-edit')"
              @copy-version="$emit('copy-version', $event)"
              @delete-version="$emit('delete-version', $event)"
            />
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import PartsVersionRowV2 from './PartsVersionRowV2.vue'
import type { PartDetail } from '@/api/patternRoom'
import type { PartEditData } from '../composables/usePartInlineEdit'
import { usePartsVersionFilter } from '../composables/usePartsVersionFilter'

const props = defineProps<{
  partsByVersion: PartDetail[]
  finalVersion: string
  projectId: number | null | undefined
  currentRoleId: number | null
  partLoading: boolean
  canManage: boolean
  /** 正在编辑的部位 ID（内联编辑状态由父级上移管理） */
  editingPartId: number | undefined
  /** 内联编辑表单 */
  editForm: PartEditData
}>()

defineEmits<{
  'set-final-version': [versionNo: string]
  'copy-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
  'start-edit': [part: PartDetail]
  'cancel-edit': []
  'save-edit': [part: PartDetail]
}>()

const partsByVersionRef = toRef(props, 'partsByVersion')
const finalVersionRef = toRef(props, 'finalVersion')
const projectIdRef = computed(() => props.projectId)
const currentRoleIdRef = toRef(props, 'currentRoleId')

const { selectedVersion, toggleVersion, toggleExpand, groupedRows } = usePartsVersionFilter(
  partsByVersionRef,
  finalVersionRef,
  projectIdRef,
  currentRoleIdRef,
)
</script>

<style scoped>
.pvt-section {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
}
.pvt-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-secondary, #475569);
  font-size: 13px;
}
.pvt-empty-parts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 16px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 13px;
}
.pvt-empty-parts svg {
  font-size: 32px;
  opacity: 0.4;
  color: var(--color-text-secondary, #475569);
}
.pvt-table-wrap {
  flex: 1;
  overflow: auto;
}
.pvt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  table-layout: fixed;
}
.pvt-table th {
  padding: 10px 12px;
  text-align: left;
  border: 1px solid #d9dce3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
}
/* td 在子组件 PartsVersionRowV2 内渲染，需 :deep() 穿透 scoped 作用域 */
:deep(.pvt-table td) {
  padding: 10px 12px;
  text-align: left;
  border: 1px solid #d9dce3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
}
.pvt-table th {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  background: #fff;
  position: sticky;
  top: 0;
  z-index: 1;
  font-size: 13px;
  text-align: center;
}
.pvt-table tbody tr:hover {
  background: transparent;
}
.pvt-table--version th {
  text-align: center;
}
/* td 在子组件内渲染，需穿透 scoped */
:deep(.pvt-table--version td) {
  text-align: center;
}
.pvt-part-name-th {
  text-align: center !important;
}
</style>
