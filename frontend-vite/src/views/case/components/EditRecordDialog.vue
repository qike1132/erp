<template>
  <UiDialog v-model:open="openModel" :title="mode === 'stockin' ? '编辑入库记录' : '编辑出库记录'" max-width-class="max-w-[480px]">
    <div class="erd-form">
      <div class="erd-field">
        <label class="erd-label">单号</label>
        <input class="erd-input" :value="form.no" disabled aria-label="单号" />
      </div>
      <div class="erd-field">
        <label class="erd-label">产品名称</label>
        <input class="erd-input" :value="form.productName" disabled aria-label="产品名称" />
      </div>
      <div class="erd-row">
        <div class="erd-field">
          <label class="erd-label">客户名称</label>
          <UiSelect
            v-model="form.customer"
            :options="mode === 'stockout' ? [{ value: '', label: '无' }, ...customerOptions] : customerOptions"
          />
        </div>
        <div class="erd-field">
          <label class="erd-label">{{ mode === 'stockin' ? '入库日期' : '出库日期' }}</label>
          <UiDatePicker v-model="form.date" style="width: 100%" />
        </div>
      </div>
      <div class="erd-field">
        <label class="erd-label">{{ mode === 'stockin' ? '入库数量' : '出库数量' }}</label>
        <input
          v-model.number="form.quantity"
          type="number"
          class="erd-input"
          :class="{ 'erd-input-error': quantityError }"
          min="1"
          step="1"
          :aria-label="mode === 'stockin' ? '入库数量' : '出库数量'"
        />
        <small v-if="quantityError" class="erd-error">{{ quantityError }}</small>
        <small v-else-if="mode === 'stockout'" class="erd-hint">数量调整会同步影响库存，库存不足时后端将拒绝保存</small>
      </div>
      <div class="erd-field">
        <label class="erd-label">备注</label>
        <textarea v-model="form.note" class="erd-textarea" rows="2" aria-label="备注" />
      </div>
    </div>
    <template #footer>
      <button class="erd-btn erd-btn-ghost" aria-label="取消" @click="openModel = false">取消</button>
      <button class="erd-btn erd-btn-primary" :disabled="!!quantityError || saving" aria-label="保存" @click="emit('save')">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * EditRecordDialog — 入库/出库记录编辑弹窗。
 * 数量前端校验：不小于 1 的整数；出库库存上限由后端行级锁校验兜底。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import type { CustomerOption } from '@/api/case'
import type { EditFormState, StockMode } from '../composables/useCaseRecordActions'

defineProps<{
  mode: StockMode
  customerOptions: CustomerOption[]
  saving: boolean
}>()

const form = defineModel<EditFormState>('form', { required: true })
const openModel = defineModel<boolean>('open', { default: false })

const emit = defineEmits<{
  save: []
}>()

const quantityError = computed(() => {
  const q = form.value.quantity
  if (!Number.isInteger(q) || q < 1) return '数量必须为不小于 1 的整数'
  return ''
})
</script>

<style scoped>
.erd-form { display: flex; flex-direction: column; }
.erd-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.erd-field { margin-bottom: 12px; }
.erd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.erd-input,
.erd-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.erd-input:focus,
.erd-textarea:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.erd-input:disabled { background: var(--color-surface, #f8fafc); color: var(--color-text-muted); }
.erd-input-error { border-color: var(--color-danger-400); }
.erd-error { color: var(--color-danger-600); font-size: 12px; margin-top: 4px; display: block; }
.erd-hint { color: var(--color-text-muted); font-size: 12px; margin-top: 4px; display: block; }
.erd-textarea { resize: vertical; }
.erd-btn {
  padding: 6px 14px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}
.erd-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.erd-btn-ghost {
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
}
.erd-btn-ghost:hover:not(:disabled) { background: var(--color-surface, #f8fafc); }
.erd-btn-primary {
  border: none;
  color: white;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
}
.erd-btn-primary:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
</style>
