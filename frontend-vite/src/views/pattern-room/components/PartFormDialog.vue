<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { toast } from '@/composables/useToast'
import type { BatchPartCreateRequest } from '@/api/patternRoom'

/** 批量新增部位表单行 */
interface PartFormRow {
  part_name: string
  supplier_id: number | null
  supplier_name: string
  fabric_name: string
  fabric_color_no: string
}

const props = defineProps<{
  open: boolean
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit-batch': [data: BatchPartCreateRequest]
}>()

const rows = ref<PartFormRow[]>([createEmptyRow()])

function createEmptyRow(): PartFormRow {
  return {
    part_name: '',
    supplier_id: null,
    supplier_name: '',
    fabric_name: '',
    fabric_color_no: '',
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

function removeRow(index: number) {
  rows.value.splice(index, 1)
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
    if (seen.has(name)) {
      toast.warning('存在重复部位')
      return
    }
    seen.add(name)
  }

  const items = filledRows.map((r) => ({
    part_name: r.part_name.trim(),
    supplier_id: r.supplier_id,
    supplier_name: r.supplier_name.trim() || null,
    fabric_name: r.fabric_name.trim() || null,
    fabric_color_no: r.fabric_color_no.trim() || null,
  }))

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
        <span class="batch-part-form__cell batch-part-form__cell--supplier">供应商</span>
        <span class="batch-part-form__cell batch-part-form__cell--fabric">布料名称</span>
        <span class="batch-part-form__cell batch-part-form__cell--color">色号</span>
        <span class="batch-part-form__cell batch-part-form__cell--action" />
      </div>

      <div class="batch-part-form__body">
        <div
          v-for="(row, index) in rows"
          :key="index"
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

          <div class="batch-part-form__cell batch-part-form__cell--supplier">
            <input
              v-model="row.supplier_name"
              class="batch-part-input"
              placeholder="供应商"
              type="text"
              maxlength="100"
            />
          </div>

          <div class="batch-part-form__cell batch-part-form__cell--fabric">
            <input
              v-model="row.fabric_name"
              class="batch-part-input"
              placeholder="布料名称"
              type="text"
              maxlength="200"
            />
          </div>

          <div class="batch-part-form__cell batch-part-form__cell--color">
            <input
              v-model="row.fabric_color_no"
              class="batch-part-input"
              placeholder="色号"
              type="text"
              maxlength="50"
            />
          </div>

          <div class="batch-part-form__cell batch-part-form__cell--action">
            <button
              v-if="rows.length > 1"
              type="button"
              class="row-remove-btn"
              title="删除此行"
              @click="removeRow(index)"
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

.batch-part-input {
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

.batch-part-input:focus {
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
