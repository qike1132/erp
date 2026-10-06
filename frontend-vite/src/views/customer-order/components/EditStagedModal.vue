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
      <!-- 分批出货计划（2026-10-06 v2）：仅订单类型，供导入/OCR 条目补设或修改手工条目 -->
      <div v-if="editStagedData.type === 'order'" class="co-form-group">
        <label class="co-label" style="display: flex; align-items: center; gap: 8px">
          <UiCheckbox
            :checked="editStagedData.shipmentPlans.length > 0"
            aria-label="是否有出货计划"
            @update:checked="toggleShipmentPlan"
          />
          有出货计划
        </label>
        <template v-if="editStagedData.shipmentPlans.length">
          <div v-for="(plan, pIdx) in editStagedData.shipmentPlans" :key="pIdx" style="display: flex; align-items: center; gap: 6px; margin-top: 8px">
            <span class="es-batch-no">第{{ pIdx + 1 }}批</span>
            <UiDatePicker
              :model-value="plan.date"
              label=""
              style="width: 150px; flex-shrink: 0"
              @update:model-value="(v: string) => updatePlanSplit(pIdx, 'date', v)"
            />
            <input
              :value="plan.quantity"
              type="number"
              class="form-number-input"
              min="1"
              step="1"
              style="width: 90px; flex-shrink: 0"
              :aria-label="`第${pIdx + 1}批数量`"
              @input="updatePlanSplit(pIdx, 'quantity', Number(($event.target as HTMLInputElement).value) || 0)"
            />
            <input
              :value="plan.note"
              type="text"
              class="form-number-input"
              style="flex: 1; min-width: 0"
              placeholder="批次备注"
              :aria-label="`第${pIdx + 1}批备注`"
              @input="updatePlanSplit(pIdx, 'note', ($event.target as HTMLInputElement).value)"
            />
            <button
              type="button"
              class="es-remove-btn"
              :aria-label="`删除第${pIdx + 1}批`"
              :disabled="editStagedData.shipmentPlans.length <= 1"
              @click="editStagedData.shipmentPlans.splice(pIdx, 1)"
            >
              <FontAwesomeIcon icon="trash" aria-hidden="true" />
            </button>
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 8px">
            <UiButton variant="outline" style="padding: 4px 12px; font-size: 12px" @click="addPlanSplit">添加一批</UiButton>
            <small v-if="splitInvalid" style="color: var(--color-danger-600); font-weight: 500">{{ splitInvalid }}</small>
          </div>
        </template>
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
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { planSplitsMessage } from '../composables/shipmentPlanRules'
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

/**
 * 分批出货计划（2026-10-06 v2）：
 * 勾选生成首行（数量=订单量）；取消清空，避免「有计划无批次」的半截状态。
 */
function toggleShipmentPlan(v: boolean) {
  if (!editStagedData.value) return
  editStagedData.value.shipmentPlans = v
    ? [{ date: '', quantity: Math.max(1, editStagedData.value.quantity), note: '' }]
    : []
}

function updatePlanSplit(idx: number, key: 'date' | 'quantity' | 'note', value: string | number) {
  const plans = editStagedData.value?.shipmentPlans
  const row = plans?.[idx]
  if (!row) return
  row[key] = value as never
}

function addPlanSplit() {
  const data = editStagedData.value
  if (!data) return
  const allocated = data.shipmentPlans.reduce((s, p) => s + (p.quantity > 0 ? p.quantity : 0), 0)
  data.shipmentPlans.push({ date: '', quantity: Math.max(0, data.quantity - allocated), note: '' })
}

/** 排满口径与行完整性校验（与录入表单同规则、同文案） */
const splitInvalid = computed(() => {
  const data = editStagedData.value
  if (!data || data.type !== 'order') return ''
  return planSplitsMessage(data.shipmentPlans, data.quantity)
})

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
/* 分批出货计划行（2026-10-06 v2） */
.es-batch-no {
  font-size: 12px; font-weight: 600; color: var(--color-primary-600);
  flex-shrink: 0; width: 38px;
}
.es-remove-btn {
  width: 28px; height: 28px; border: none; border-radius: 7px;
  background: var(--color-danger-50); color: var(--color-danger-500);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; font-size: 12px; transition: background 0.2s ease;
}
.es-remove-btn:hover:not(:disabled) { background: var(--color-danger-100); }
.es-remove-btn:disabled { opacity: 0.35; cursor: not-allowed; }
</style>
