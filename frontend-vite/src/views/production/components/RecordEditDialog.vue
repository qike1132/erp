<template>
  <!-- 本弹窗是从「生产明细」抽屉里点「改」打开的：抽屉是 PrimeVue Drawer，
       其遮罩 z 由 PrimeVue 定为 2100（main.ts 的 zIndex.modal）。故这里必须用
       超出该层的嵌套层级（--z-overlay/modal-nested，2200/2210），否则会被遮罩压住。 -->
  <UiDialog
    :open="open"
    title="编辑生产记录"
    overlay-z-class="z-[var(--z-overlay-nested)]"
    content-z-class="z-[var(--z-modal-nested)]"
    @update:open="emit('update:open', $event)"
  >
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

// 只保留本弹窗可改的字段：单价与备注不在此编辑（产值 = 单价 × 数量，改数量时单价不动）。
const form = reactive({
  production_date: '',
  quantity: 0,
})

const original = reactive({ production_date: '', quantity: 0 })

watch(
  () => [props.open, props.record] as const,
  () => {
    if (!props.open || !props.record) return
    form.production_date = props.record.production_date
    form.quantity = props.record.quantity
    Object.assign(original, form)
    error.value = ''
  },
  { immediate: true },
)

/** 只提交改动过的字段：后端 PUT 接受部分字段，未改动的字段不该被覆盖 */
function changedFields(): Record<string, unknown> {
  const diff: Record<string, unknown> = {}
  if (form.production_date !== original.production_date) diff.production_date = form.production_date
  if (form.quantity !== original.quantity) diff.quantity = form.quantity
  return diff
}

async function submit() {
  if (!props.record) return
  if (!form.quantity || form.quantity <= 0) {
    error.value = '生产数量必须大于 0'
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
</script>
