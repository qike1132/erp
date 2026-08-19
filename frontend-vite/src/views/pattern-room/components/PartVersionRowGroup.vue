<template>
  <tr
    v-for="(part, idx) in group.items"
    :key="part.id ?? `${group.part_name}-${idx}`"
    :class="{ 'pdp-row--editing': editingPartId === part.id }"
  >
    <td v-if="idx === 0" :rowspan="group.rowSpan" class="pdp-part-name-col">
      <div class="pdp-part-name-cell">
        <span>{{ group.part_name }}</span>
        <button
          v-if="selectedVersion[group.part_name] && group.totalVersionCount > 1"
          class="pdp-expand-btn"
          :title="group.collapsed ? '展开所有版本' : '折叠其他版本'"
          @click.stop="emit('toggle-expand', group.part_name)"
        >
          <i
            :class="['fas', group.collapsed ? 'fa-chevron-down' : 'fa-chevron-up']"
            aria-hidden="true"
          />
        </button>
      </div>
    </td>
    <td class="pdp-version-col">
      <button
        v-if="part.version_no"
        class="pdp-vp-chip"
        :class="{ 'pdp-vp-chip--active': selectedVersion[group.part_name] === part.version_no, 'pdp-vp-chip--disabled': group.totalVersionCount <= 1 }"
        :title="group.totalVersionCount <= 1 ? '该部位只有一个版本' : (selectedVersion[group.part_name] === part.version_no ? '点击取消选择，显示所有版本' : '选择 ' + part.version_no + ' 为最终版本')"
        :disabled="!canManage || group.totalVersionCount <= 1"
        @click.stop="emit('toggle-version', group.part_name, part.version_no!)"
      >
        {{ part.version_no }}
      </button>
      <span v-else>-</span>
    </td>
    <td>
      <input
        v-if="editingPartId === part.id"
        v-model="editForm.supplier_name"
        class="pdp-inline-input"
        placeholder="供应商"
      />
      <template v-else>{{ part.supplier_name || '-' }}</template>
    </td>
    <td>
      <input
        v-if="editingPartId === part.id"
        v-model="editForm.fabric_name"
        class="pdp-inline-input"
        placeholder="布料名称"
      />
      <template v-else>{{ part.fabric_name || '-' }}</template>
    </td>
    <td>
      <input
        v-if="editingPartId === part.id"
        v-model="editForm.fabric_color_no"
        class="pdp-inline-input"
        placeholder="色号"
      />
      <template v-else>{{ part.fabric_color_no || '-' }}</template>
    </td>
    <td class="pdp-actions-col">
      <div v-if="editingPartId === part.id" class="pdp-row-actions">
        <button
          type="button"
          class="pdp-action-btn pdp-action-btn--success"
          title="保存"
          @click="emit('save-edit', part)"
        >
          <i class="fas fa-check" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="pdp-action-btn pdp-action-btn--muted"
          title="取消"
          @click="emit('cancel-edit')"
        >
          <i class="fas fa-times" aria-hidden="true" />
        </button>
      </div>
      <div v-else class="pdp-row-actions">
        <button
          v-if="group.collapsed || part.version_no === group.latestVersionNo"
          type="button"
          class="pdp-action-btn pdp-action-btn--info"
          title="复制版本"
          @click="emit('copy-version', part)"
        >
          <i class="fas fa-copy" aria-hidden="true" />
        </button>
        <span v-else class="pdp-action-placeholder" />
        <button
          type="button"
          class="pdp-action-btn pdp-action-btn--warning"
          :title="part.id == null ? '历史快照，无法编辑' : '修改版本'"
          :disabled="!canManage || part.id == null"
          @click="emit('start-edit', part)"
        >
          <i class="fas fa-pen" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="pdp-action-btn pdp-action-btn--danger"
          title="删除版本"
          @click="emit('delete-version', part)"
        >
          <i class="fas fa-trash-alt" aria-hidden="true" />
        </button>
      </div>
    </td>
  </tr>
</template>

<script setup lang="ts">
import type { PartDetail } from '@/api/patternRoom'
import type { PartGroupRow, EditFormState } from '../composables/useProjectDetail'

defineProps<{
  group: PartGroupRow
  editingPartId: number | undefined
  editForm: EditFormState
  canManage: boolean
  selectedVersion: Record<string, string | null>
}>()

const emit = defineEmits<{
  'toggle-expand': [partName: string]
  'toggle-version': [partName: string, versionNo: string]
  'start-edit': [part: PartDetail]
  'save-edit': [part: PartDetail]
  'cancel-edit': []
  'copy-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
}>()
</script>

<style scoped>
.pdp-part-name-col {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
  text-align: center !important;
}
.pdp-part-name-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pdp-expand-btn {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  font-size: 9px;
  color: var(--color-warning-500, #ff9f43);
  background: #fff;
  border: 1px solid var(--color-warning-300, #fdba74);
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}
.pdp-expand-btn:hover {
  color: #fff;
  background: var(--color-warning-500, #ff9f43);
  border-color: var(--color-warning-500, #ff9f43);
}
.pdp-version-col {
  text-align: center;
  color: var(--color-text-primary, #1a1a2e);
}
.pdp-vp-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 500;
  font-family: inherit;
  color: var(--color-text-muted, #94a3b8);
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}
.pdp-vp-chip:hover {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-300, #fdba74);
}
.pdp-vp-chip--active {
  color: #fff;
  background: linear-gradient(135deg, #ff9f43, #ff8c1f);
  border-color: #ff8c1f;
  box-shadow: 0 1px 4px rgba(255, 159, 67, 0.3);
}
.pdp-vp-chip--active:hover {
  color: #fff;
  background: linear-gradient(135deg, #ff8c1f, #e67e22);
  border-color: #e67e22;
}
.pdp-vp-chip--disabled,
.pdp-vp-chip--disabled:hover {
  cursor: not-allowed;
  opacity: 0.6;
  color: var(--color-text-muted, #94a3b8);
  background: #f8fafc;
  border-color: #e2e8f0;
  box-shadow: none;
}
.pdp-actions-col {
  padding: 6px 10px !important;
}
.pdp-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pdp-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  font-size: 12px;
  font-family: inherit;
  border: 1px solid;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.pdp-action-btn i {
  font-size: 10px;
}
.pdp-action-btn--info {
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
  border-color: var(--color-primary-200, #bfdbfe);
}
.pdp-action-btn--info:hover {
  background: var(--color-primary-100, #dbeafe);
  border-color: var(--color-primary-400, #60a5fa);
}
.pdp-action-placeholder {
  display: inline-flex;
  width: 26px;
  height: 26px;
  visibility: hidden;
}
.pdp-action-btn--warning {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-200, #fed7aa);
}
.pdp-action-btn--warning:hover {
  background: var(--color-warning-100, #ffedd5);
  border-color: var(--color-warning-400, #fb923c);
}
.pdp-action-btn--danger {
  color: var(--color-danger-600, #dc2626);
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-200, #fecaca);
}
.pdp-action-btn--danger:hover {
  background: var(--color-danger-100, #fee2e2);
  border-color: var(--color-danger-400, #f87171);
}
.pdp-action-btn--success {
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
  border-color: var(--color-success-200, #bbf7d0);
}
.pdp-action-btn--success:hover {
  background: var(--color-success-100, #dcfce7);
  border-color: var(--color-success-400, #4ade80);
}
.pdp-action-btn--muted {
  color: var(--color-text-secondary, #6b7280);
  background: #f9fafb;
  border-color: #d1d5db;
}
.pdp-action-btn--muted:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}
.pdp-row--editing {
  background: #fefce8;
}
.pdp-inline-input {
  width: 100%;
  max-width: 100%;
  padding: 4px 6px;
  border: 1px solid var(--color-warning-400, #fb923c);
  border-radius: 4px;
  font-size: 12px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  background: #fff;
  color: var(--color-text-primary, #1a1a2e);
}
.pdp-inline-input:focus {
  border-color: var(--color-warning-500, #ff9f43);
  box-shadow: 0 0 0 2px var(--color-warning-100, #ffedd5);
}
</style>