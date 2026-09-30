<template>
  <UiDialog :open="open" title="编辑生产记录" @update:open="emit('update:open', $event)">
    <div v-if="record" class="flex flex-col gap-4">
      <div class="rounded-lg bg-surface px-3 py-2 text-xs text-text-secondary">
        {{ record.product_name }} · {{ record.barcode || '无 69 码' }} · 原录单人 {{ record.created_by || '—' }}
      </div>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">生产日期</span>
        <input v-model="form.production_date" data-test="edit-date" type="date" class="rounded-lg border border-border-light px-3 py-2 text-sm" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">数量</span>
        <input v-model.number="form.quantity" data-test="edit-quantity" type="number" min="0" class="rounded-lg border border-border-light px-3 py-2 text-sm tabular-nums" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">单价</span>
        <input v-model.number="form.unit_price" data-test="edit-price" type="number" min="0" step="0.01" class="rounded-lg border border-border-light px-3 py-2 text-sm tabular-nums" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">备注</span>
        <input v-model="form.remark" data-test="edit-remark" type="text" class="rounded-lg border border-border-light px-3 py-2 text-sm" />
      </label>

      <p v-if="error" class="text-xs font-semibold text-danger-600">{{ error }}</p>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <button class="rounded-lg border border-border-light px-4 py-2 text-sm font-semibold" @click="emit('update:open', false)">取消</button>
        <button data-test="edit-submit" class="rounded-lg bg-primary-600 px-4 py-2 text-sm font-bold text-white" :disabled="saving" @click="submit">
          保存
        </button>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import UiDialog from '@/components/ui/UiDialog.vue'
import { dailyProductionApi } from '@/api/production'
import type { DailyProductionRecord } from '@/types'

const props = defineProps<{
  open: boolean
  record: DailyProductionRecord | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: []
}>()

const saving = ref(false)
const error = ref('')

const form = reactive({
  production_date: '',
  quantity: 0,
  unit_price: 0,
  remark: '',
})

const original = reactive({ production_date: '', quantity: 0, unit_price: 0, remark: '' })

watch(
  () => [props.open, props.record] as const,
  () => {
    if (!props.open || !props.record) return
    form.production_date = props.record.production_date
    form.quantity = props.record.quantity
    form.unit_price = props.record.unit_price
    form.remark = props.record.remark ?? ''
    Object.assign(original, form)
    error.value = ''
  },
  { immediate: true },
)

/** 只提交改动过的字段：后端 PUT 接受部分字段，未改动的字段不该被覆盖（尤其是没动单价时不该用 0 覆盖） */
function changedFields(): Record<string, unknown> {
  const diff: Record<string, unknown> = {}
  if (form.production_date !== original.production_date) diff.production_date = form.production_date
  if (form.quantity !== original.quantity) diff.quantity = form.quantity
  if (form.unit_price !== original.unit_price) diff.unit_price = form.unit_price
  if (form.remark !== original.remark) diff.remark = form.remark
  return diff
}

async function submit() {
  if (!props.record) return
  if (!form.quantity || form.quantity <= 0) {
    error.value = '生产数量必须大于 0'
    return
  }
  // 数字输入框被清空时 v-model.number 会留下空串；若直接提交，后端会以晦涩的 422 拒绝。
  if (isBlank(form.unit_price)) {
    error.value = '单价不能为空'
    return
  }
  const diff = changedFields()
  if (!Object.keys(diff).length) {
    emit('update:open', false)
    return
  }

  saving.value = true
  error.value = ''
  try {
    await dailyProductionApi.updateRecord(props.record.id, diff)
    emit('saved')
    emit('update:open', false)
  } catch (e: unknown) {
    // FastAPI 校验失败时 detail 是数组，直接当字符串用会把原始 JSON 摊给用户看。
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '保存失败'
  } finally {
    saving.value = false
  }
}

/** 数字输入被清空时是空串（v-model.number 无法解析），也覆盖 null/undefined/NaN */
function isBlank(v: unknown): boolean {
  return v === '' || v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))
}
</script>
