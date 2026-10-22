<template>
  <tr
    v-for="(part, idx) in group.items"
    :key="part.id ?? `${group.part_name}-${idx}`"
    :class="{ 'pvt-row--editing': editingPartId === part.id }"
  >
    <td v-if="idx === 0" :rowspan="group.rowSpan" class="pvt-part-name-col">
      <div class="pvt-part-name-cell">
        <span>{{ group.part_name }}</span>
        <button
          v-if="selectedVersion[group.part_name] && group.totalVersionCount > 1"
          class="pvt-expand-btn"
          :title="group.collapsed ? '展开所有版本' : '折叠其他版本'"
          :aria-label="group.collapsed ? '展开所有版本' : '折叠其他版本'"
          :aria-expanded="group.collapsed ? 'false' : 'true'"
          @click.stop="$emit('toggle-expand', group.part_name)"
        >
          <FontAwesomeIcon :icon="group.collapsed ? 'chevron-down' : 'chevron-up'"
                           aria-hidden="true"
          />
        </button>
      </div>
    </td>
    <td class="pvt-version-col">
      <button
        v-if="part.version_no"
        v-bind="selectionItemAttrs(selectedVersion[group.part_name] === part.version_no)"
        class="pvt-vp-chip"
        :class="{ 'pvt-vp-chip--active': selectedVersion[group.part_name] === part.version_no, 'pvt-vp-chip--disabled': group.totalVersionCount <= 1 }"
        :title="group.totalVersionCount <= 1 ? '该部位只有一个版本' : (selectedVersion[group.part_name] === part.version_no ? '点击取消选择，显示所有版本' : '选择 ' + part.version_no + ' 为最终版本')"
        :disabled="!canManage || group.totalVersionCount <= 1"
        @click.stop="$emit('toggle-version', group.part_name, part.version_no!)"
      >
        {{ part.version_no }}
      </button>
      <span v-else>-</span>
    </td>
    <td v-for="field in PART_EDIT_FIELDS" :key="field.key">
      <PartFieldCombobox
        v-if="editingPartId === part.id && field.historyCandidates"
        v-model="editForm[field.key]"
        input-class="pvt-inline-input"
        :options="candidatesFor(field.key)"
        :placeholder="field.placeholder"
        :maxlength="field.inlineMaxlength"
        :empty-hint="field.historyCandidates.hint"
        :aria-label="`${group.part_name} ${part.version_no ?? ''} 的${field.label}`"
      />
      <input
        v-else-if="editingPartId === part.id"
        v-model="editForm[field.key]"
        class="pvt-inline-input"
        :placeholder="field.placeholder"
        :maxlength="field.inlineMaxlength"
        :aria-label="`${group.part_name} ${part.version_no ?? ''} 的${field.label}`"
      />
      <template v-else>{{ part[field.key] || '-' }}</template>
    </td>
    <td class="pvt-actions-col">
      <div v-if="editingPartId === part.id" class="pvt-row-actions">
        <button
          type="button"
          class="pvt-action-btn pvt-action-btn--success"
          title="保存"
          :aria-label="`保存修改：${rowTarget(part, group)}`"
          @click="saveEdit(part)"
        >
          <FontAwesomeIcon icon="check" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="pvt-action-btn pvt-action-btn--muted"
          title="取消"
          :aria-label="`取消修改：${rowTarget(part, group)}`"
          @click="cancelEdit()"
        >
          <FontAwesomeIcon icon="times" aria-hidden="true" />
        </button>
      </div>
      <div v-else class="pvt-row-actions">
        <button
          v-if="group.collapsed || part.version_no === group.latestVersionNo"
          type="button"
          class="pvt-action-btn pvt-action-btn--info"
          :title="part.id == null ? '历史快照，无法复制' : '复制版本'"
          :aria-label="actionLabel('复制版本', part, group)"
          :disabled="!canManage || part.id == null"
          @click="$emit('copy-version', part)"
        >
          <FontAwesomeIcon icon="copy" aria-hidden="true" />
        </button>
        <span v-else class="pvt-action-placeholder" />
        <button
          type="button"
          class="pvt-action-btn pvt-action-btn--warning"
          :title="part.id == null ? '历史快照，无法编辑' : '修改版本'"
          :aria-label="actionLabel('修改版本', part, group)"
          :disabled="!canManage || part.id == null"
          @click="startEdit(part)"
        >
          <FontAwesomeIcon icon="pen" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="pvt-action-btn pvt-action-btn--danger"
          :title="part.id == null ? '历史快照，无法删除' : '删除版本'"
          :aria-label="actionLabel('删除版本', part, group)"
          :disabled="!canManage || part.id == null"
          @click="$emit('delete-version', part)"
        >
          <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
        </button>
      </div>
    </td>
  </tr>
</template>

<script setup lang="ts">
import type { PartDetail } from '@/api/patternRoom'
import type { GroupedRow } from '../composables/usePartsVersionFilter'
import PartFieldCombobox from './PartFieldCombobox.vue'
import { PART_EDIT_FIELDS, injectPartInlineEdit } from '../composables/usePartInlineEdit'
import { selectionItemAttrs } from '@/composables/useSelectionA11y'

defineProps<{
  group: GroupedRow
  canManage: boolean
  selectedVersion: Record<string, string | null>
}>()

// 编辑态（editingPartId / editForm / startEdit / saveEdit / cancelEdit）经
// provide/inject 直连，避免经 ProjectDetailPanel、PartsVersionTableV2 两层透传
const { editingPartId, editForm, startEdit, saveEdit, cancelEdit, candidatesFor } = injectPartInlineEdit()

defineEmits<{
  'toggle-expand': [partName: string]
  'toggle-version': [partName: string, versionNo: string]
  'copy-version': [part: PartDetail]
  'delete-version': [part: PartDetail]
}>()

/**
 * 行内图标按钮的可访问名（审查 A11Y-21）。
 *
 * 这些按钮只有图标、没有可见文字，原来仅靠 `title` 命名，两个问题：
 *   1. 触屏没有 hover，看不到提示；
 *   2. `disabled` 时多数读屏器不播报 `title`，而本表恰恰会把「历史快照」行置灰 ——
 *      用户只会听到一串「按钮，不可用」，不知道是哪个操作、为什么不可用。
 * 所以 aria-label 里同时带上「动作 + 部位 + 版本」，并保留禁用原因。
 */
function rowTarget(part: PartDetail, group: GroupedRow): string {
  return `${group.part_name} ${part.version_no ?? ''}`.trim()
}

function actionLabel(action: string, part: PartDetail, group: GroupedRow): string {
  const target = rowTarget(part, group)
  return part.id == null ? `${action}（${target}：历史快照，不可操作）` : `${action}：${target}`
}
</script>

<style scoped>
.pvt-part-name-col {
  font-weight: 500;
  color: var(--color-text-primary, #1a1a2e);
  vertical-align: middle;
  text-align: center !important;
}
.pvt-part-name-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pvt-expand-btn {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 24×24：WCAG 2.5.8 Target Size (Minimum) 下限，原 20×20 不达标（审查 A11Y-14） */
  width: 24px;
  height: 24px;
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
.pvt-expand-btn:hover {
  color: #fff;
  background: var(--color-warning-500, #ff9f43);
  border-color: var(--color-warning-500, #ff9f43);
}
.pvt-vp-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  /* 24px：WCAG 2.5.8 下限，原 22px 不达标（审查 A11Y-14） */
  height: 24px;
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
.pvt-vp-chip:hover {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-300, #fdba74);
}
.pvt-vp-chip--active {
  color: #fff;
  background: linear-gradient(135deg, #ff9f43, #ff8c1f);
  border-color: #ff8c1f;
  box-shadow: 0 1px 4px rgba(255, 159, 67, 0.3);
}
.pvt-vp-chip--active:hover {
  color: #fff;
  background: linear-gradient(135deg, #ff8c1f, #e67e22);
  border-color: #e67e22;
}
.pvt-vp-chip--disabled,
.pvt-vp-chip--disabled:hover {
  cursor: not-allowed;
  opacity: 0.6;
  color: var(--color-text-muted, #94a3b8);
  background: #f8fafc;
  border-color: #e2e8f0;
  box-shadow: none;
}
.pvt-version-col {
  text-align: center;
  color: var(--color-text-primary, #1a1a2e);
}
.pvt-actions-col {
  padding: 6px 10px !important;
}
.pvt-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pvt-action-btn {
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
.pvt-action-btn i {
  font-size: 10px;
}
.pvt-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  pointer-events: none;
}
.pvt-action-btn--info {
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
  border-color: var(--color-primary-200, #bfdbfe);
}
.pvt-action-btn--info:hover {
  background: var(--color-primary-100, #dbeafe);
  border-color: var(--color-primary-400, #60a5fa);
}
.pvt-action-placeholder {
  display: inline-flex;
  width: 26px;
  height: 26px;
  visibility: hidden;
}
.pvt-action-btn--warning {
  color: var(--color-warning-600, #ea580c);
  background: var(--color-warning-50, #fff7ed);
  border-color: var(--color-warning-200, #fed7aa);
}
.pvt-action-btn--warning:hover {
  background: var(--color-warning-100, #ffedd5);
  border-color: var(--color-warning-400, #fb923c);
}
.pvt-action-btn--danger {
  color: var(--color-danger-600, #dc2626);
  background: var(--color-danger-50, #fef2f2);
  border-color: var(--color-danger-200, #fecaca);
}
.pvt-action-btn--danger:hover {
  background: var(--color-danger-100, #fee2e2);
  border-color: var(--color-danger-400, #f87171);
}
.pvt-action-btn--success {
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
  border-color: var(--color-success-200, #bbf7d0);
}
.pvt-action-btn--success:hover {
  background: var(--color-success-100, #dcfce7);
  border-color: var(--color-success-400, #4ade80);
}
.pvt-action-btn--muted {
  color: var(--color-text-secondary, #6b7280);
  background: #f9fafb;
  border-color: #d1d5db;
}
.pvt-action-btn--muted:hover {
  background: #f3f4f6;
  border-color: #9ca3af;
}
.pvt-row--editing {
  background: #fefce8;
}
/* 该 class 既用在原生 <input> 上，也经 input-class 落到 PartFieldCombobox 子组件的 input 上；
   后者只带子组件 scope id → 用 :deep 穿透，两条路径都命中。 */
:deep(.pvt-inline-input) {
  width: 100%;
  max-width: 100%;
  padding: 4px 6px;
  border: 1px solid var(--color-warning-400, #fb923c);
  border-radius: 4px;
  font-size: 12px;
  font-family: inherit;
  box-sizing: border-box;
  background: #fff;
  color: var(--color-text-primary, #1a1a2e);
}
:deep(.pvt-inline-input:focus-visible) {
  border-color: var(--color-warning-500, #ff9f43);
  box-shadow: 0 0 0 2px var(--color-warning-100, #ffedd5);
}
</style>