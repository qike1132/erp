<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import PartFieldCombobox from './PartFieldCombobox.vue'
import type { BatchPartCreateRequest } from '@/api/patternRoom'
import {
  PART_EDIT_FIELDS,
  createEmptyEditData,
  injectPartInlineEdit,
  type PartEditData,
} from '../composables/usePartInlineEdit'

// 候选来源经页面级 provide 下发（PatternRoomView），此处只消费不加载。
const { candidatesFor } = injectPartInlineEdit()

/**
 * 批量新增部位表单行。
 * `uid` 用于 v-for 稳定 key：原先用 index 作 key，删除中间行时输入框组件会被
 * 复用错位（焦点/原生输入状态串行）。
 */
interface PartFormRow extends PartEditData {
  uid: number
  part_name: string
}

const props = defineProps<{
  open: boolean
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit-batch': [data: BatchPartCreateRequest]
}>()

/** 行 uid 自增计数器（仅用于 key，无业务含义） */
let nextRowUid = 1

const rows = ref<PartFormRow[]>([createEmptyRow()])

function createEmptyRow(): PartFormRow {
  return {
    uid: nextRowUid++,
    part_name: '',
    ...createEmptyEditData(),
  }
}

function resetRows() {
  rows.value = [createEmptyRow()]
}

watch(
  () => props.open,
  (visible) => {
    if (visible) resetRows()
  },
)

function addRow() {
  rows.value.push(createEmptyRow())
}

function removeRow(uid: number) {
  rows.value = rows.value.filter((r) => r.uid !== uid)
  if (rows.value.length === 0) {
    rows.value.push(createEmptyRow())
  }
}

const filledCount = computed(() => rows.value.filter((r) => r.part_name.trim().length > 0).length)

const canSubmit = computed(() => filledCount.value > 0 && !props.submitting)

function handleSubmit() {
  const filledRows = rows.value.filter((r) => r.part_name.trim().length > 0)

  const seen = new Set<string>()
  for (const row of filledRows) {
    const name = row.part_name.trim()
    if (seen.has(name)) return
    seen.add(name)
  }

  const items = filledRows.map((r) => ({
    part_name: r.part_name.trim(),
    supplier_id: null,
    ...Object.fromEntries(PART_EDIT_FIELDS.map((f) => [f.key, r[f.key].trim() || null])),
  })) as BatchPartCreateRequest['items']

  emit('submit-batch', { items })
}

function closeDialog() {
  emit('update:open', false)
}
</script>

<template>
  <UiDialog
    :open="open"
    title="新增部位"
    max-width-class="max-w-[800px]"
    @update:open="$emit('update:open', $event)"
  >
    <div class="batch-part-form">
      <div class="batch-part-form__head" aria-hidden="true">
        <span class="batch-part-form__cell batch-part-form__cell--name">
          部位名称 <span class="required-mark">*</span>
        </span>
        <span
          v-for="field in PART_EDIT_FIELDS"
          :key="field.key"
          class="batch-part-form__cell"
          :class="`batch-part-form__cell--${field.modifier}`"
        >{{ field.label }}</span>
        <span class="batch-part-form__cell batch-part-form__cell--action" />
      </div>

      <div class="batch-part-form__body">
        <div
          v-for="row in rows"
          :key="row.uid"
          class="batch-part-form__row"
        >
          <div class="batch-part-form__cell batch-part-form__cell--name">
            <input
              v-model="row.part_name"
              class="batch-part-input"
              placeholder="如 身体，头部"
              type="text"
              maxlength="100"
            />
          </div>

          <div
            v-for="field in PART_EDIT_FIELDS"
            :key="field.key"
            class="batch-part-form__cell"
            :class="`batch-part-form__cell--${field.modifier}`"
          >
            <PartFieldCombobox
              v-if="field.historyCandidates"
              v-model="row[field.key]"
              input-class="batch-part-input"
              :options="candidatesFor(field.key)"
              :placeholder="field.placeholder"
              :maxlength="field.formMaxlength"
              :empty-hint="field.historyCandidates.hint"
            />
            <input
              v-else
              v-model="row[field.key]"
              class="batch-part-input"
              :placeholder="field.placeholder"
              type="text"
              :maxlength="field.formMaxlength"
            />
          </div>

          <div class="batch-part-form__cell batch-part-form__cell--action">
            <button
              v-if="rows.length > 1"
              type="button"
              class="row-remove-btn"
              title="删除此行"
              @click="removeRow(row.uid)"
            >
              <FontAwesomeIcon icon="times" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <button type="button" class="add-row-btn" aria-label="添加行" @click="addRow">
        <FontAwesomeIcon icon="plus" aria-hidden="true" />
        添加行
      </button>
    </div>

    <template #footer>
      <div class="batch-part-form__footer">
        <UiButton variant="ghost" @click="closeDialog">取消</UiButton>
        <UiButton
          variant="primary"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="handleSubmit"
        >
          提交（{{ filledCount }} 个）
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<style scoped>
.batch-part-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.batch-part-form__head,
.batch-part-form__row {
  display: grid;
  grid-template-columns: 1.5fr 1.5fr 1.25fr 1fr 36px;
  gap: 12px;
  align-items: center;
}

.batch-part-form__head {
  padding-bottom: 8px;
  border-bottom: 1px solid var(--color-border-light);
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.batch-part-form__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 48vh;
  overflow-y: auto;
  padding-right: 4px;
}

.batch-part-form__cell {
  min-width: 0;
}

.batch-part-form__cell--action {
  display: flex;
  justify-content: center;
}

.required-mark {
  color: var(--color-danger-500, #ef4444);
}

/* 该 class 同时用在原生 <input>（本组件模板内）与 PartFieldCombobox 的 input（子组件内），
   后者只带子组件 scope id，父组件 scoped 规则够不到 → 用 :deep 穿透，两条路径都命中。 */
:deep(.batch-part-input) {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  background: #fff;
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

:deep(.batch-part-input:focus) {
  border-color: var(--color-primary-500);
}

.row-remove-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  transition: all 0.15s;
}

.row-remove-btn:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

.add-row-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-primary-600);
  border: 1px dashed var(--color-primary-300);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.add-row-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-500);
}

.batch-part-form__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
