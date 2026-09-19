<template>
  <UiDialog
    v-model:open="openModel"
    :title="editStagedData?.type === 'order' ? '编辑暂存订单' : '编辑暂存备货'"
  >
    <template v-if="editStagedData">
      <div class="co-form-group">
        <label class="co-label">客户名称</label>
        <UiSelect v-model="editStagedData.customer" style="width: 100%" :options="customerOptions" />
      </div>
      <div class="co-form-group">
        <label class="co-label">{{ editStagedData.type === 'order' ? '订单时间' : '备货时间' }}</label>
        <UiDatePicker v-model="editStagedData.date" style="width: 100%" />
      </div>
      <div class="co-form-group">
        <label class="co-label">产品名称</label>
        <UiInput :model-value="editStagedData.productName" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="es-quantity">{{ editStagedData.type === 'order' ? '订单数量' : '备货数量' }}</label>
        <input
          id="es-quantity"
          v-model.number="editStagedData.quantity"
          type="number"
          class="form-number-input"
          :class="{ 'form-input-invalid': quantityInvalid }"
          :min="QUANTITY_MIN"
          :max="QUANTITY_MAX"
          step="1"
          style="width: 100%"
          name="quantity"
          autocomplete="off"
          :aria-label="editStagedData.type === 'order' ? '订单数量' : '备货数量'"
          :aria-invalid="quantityAriaInvalid(editStagedData.quantity)"
          aria-describedby="es-quantity-error"
        />
        <p v-if="quantityInvalid" id="es-quantity-error" class="field-error-text" role="alert">
          {{ QUANTITY_RANGE_MESSAGE }}
        </p>
      </div>
      <div v-if="editStagedData.type === 'order'" class="co-form-group">
        <label class="co-label">抵扣备货数量</label>
        <input v-model.number="editStagedData.deductQuantity" type="number" class="form-number-input" min="0" :max="Math.min(editStagedData.quantity, editAvailableStock)" step="1" style="width: 100%" name="deduct-quantity" autocomplete="off" aria-label="抵扣备货数量" />
        <small v-if="editAvailableStock > 0" style="color: var(--color-success-700); margin-top: 4px; display: block">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 可用备货: <strong>{{ editAvailableStock }}</strong> 件
        </small>
      </div>
      <div class="co-form-group">
        <label class="co-label">备注</label>
        <textarea v-model="editStagedData.note" rows="2" class="co-textarea" aria-label="备注" />
      </div>
    </template>
    <template #footer>
      <UiButton variant="outline" @click="openModel = false"> 取消 </UiButton>
      <UiButton variant="primary" @click="saveEditStaged"> 保存 </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import type { StagedItem } from '../composables/types'
import {
  QUANTITY_MAX,
  QUANTITY_MIN,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
  quantityAriaInvalid,
} from '../composables/quantityRange'

const props = defineProps<{
  open: boolean
  editAvailableStock: number
  customerOptions: { label: string; value: string }[]
  saveEditStaged: () => void
}>()

const editStagedData = defineModel<StagedItem | null>('editStagedData')

/** 数量越界时的字段级错误态（与主录入共用同一范围与文案） */
const quantityInvalid = computed(() => isQuantityOutOfRange(editStagedData.value?.quantity))

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})
</script>

<style scoped>
.co-form-group { margin-bottom: 14px; }
.co-label {
  display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; color: var(--color-text-secondary);
}
.co-textarea {
  width: 100%; border: 1px solid var(--color-border, #cbd5e1); border-radius: 10px;
  padding: 8px 12px; font-size: 14px; resize: vertical; outline: none;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease; font-family: inherit;
}
.co-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.co-textarea:focus {
  border-color: var(--color-primary-400); background: white;
  box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}
.co-textarea::placeholder { color: var(--color-text-muted); font-size: 14px; font-weight: 400; opacity: 1; }
.form-number-input {
  width: 100%; padding: 8px 12px; border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px; font-size: 14px; color: var(--color-text); font-family: inherit;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease; outline: none;
  -moz-appearance: textfield;
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-number-input::-webkit-inner-spin-button, .form-number-input::-webkit-outer-spin-button { opacity: 1; }
.form-number-input:focus {
  border-color: var(--color-primary-400); background: white;
  box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}
</style>
