<template>
  <UiDialog v-model:open="openModel" :title="isDeduction ? '编辑备货抵扣' : '编辑出货'">
    <template v-if="form">
      <div class="co-form-group">
        <label class="co-label" for="eso-customer">客户名称</label>
        <UiSelect
          id="eso-customer"
          v-model="form.customer"
          style="width: 100%"
          :options="customerOptions"
          :disabled="isDeduction"
        />
        <p v-if="isDeduction" class="field-hint-text">抵扣出货的客户由订单与备货带出，不可修改</p>
      </div>
      <div class="co-form-group">
        <label class="co-label">出货时间</label>
        <UiDatePicker v-model="form.date" style="width: 100%" />
      </div>
      <div class="co-form-group">
        <label class="co-label">产品名称</label>
        <!-- 产品不可改：换产品等于换一条出货记录，后端 StockOutUpdate 也没有 product_id -->
        <UiInput :model-value="form.productName" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="eso-quantity">出货数量</label>
        <input
          id="eso-quantity"
          v-model.number="form.quantity"
          type="number"
          class="form-number-input"
          :class="{ 'form-input-invalid': quantityInvalid }"
          :min="QUANTITY_MIN"
          :max="QUANTITY_MAX"
          step="1"
          style="width: 100%"
          name="quantity"
          autocomplete="off"
          aria-label="出货数量"
          :aria-invalid="quantityAriaInvalid(form.quantity)"
          aria-describedby="eso-quantity-error"
        />
        <p v-if="quantityInvalid" id="eso-quantity-error" class="field-error-text" role="alert">
          {{ QUANTITY_RANGE_MESSAGE }}
        </p>
      </div>
      <div class="co-form-group">
        <label class="co-label" for="eso-note">备注</label>
        <textarea id="eso-note" v-model="form.note" rows="2" class="co-textarea" aria-label="备注" />
      </div>
    </template>
    <template #footer>
      <UiButton variant="outline" :disabled="saving" @click="openModel = false"> 取消 </UiButton>
      <UiButton variant="primary" :disabled="saving || quantityInvalid" @click="saveStockoutEdit">
        {{ saving ? '保存中…' : '保存' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * EditStockoutModal.vue — 出货/备货抵扣行编辑弹窗（报表页出货/抵扣流水）。
 *
 * 字段与后端 `PUT /stock/out/edit/{id}` 的 `StockOutUpdate` 一一对应：
 * 数量 / 客户 / 出货日期 / 备注。产品刻意不可改。抵扣行（isDeduction）客户由
 * 订单/备货带出，禁用客户下拉且后端也会忽略传入的 customer。
 * 改数量时后端按差值同步调整产品库存、备货可用量并重算订单状态。
 *
 * 弹窗只负责呈现与收集，保存流程（调接口、失效缓存、刷新列表）在 useReportRowActions。
 */
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import type { StockoutEditForm } from '../composables/useReportRowActions'
import {
  QUANTITY_MAX,
  QUANTITY_MIN,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
  quantityAriaInvalid,
} from '@/utils/quantity'

const props = defineProps<{
  open: boolean
  customerOptions: { label: string; value: string }[]
  saving: boolean
  saveStockoutEdit: () => void
  /** 抵扣行：客户不可改 */
  isDeduction?: boolean
}>()

const form = defineModel<StockoutEditForm | null>('form')

const isDeduction = computed(() => props.isDeduction ?? false)
const quantityInvalid = computed(() => isQuantityOutOfRange(form.value?.quantity))

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
.field-hint-text { margin: 4px 0 0; font-size: 12px; color: var(--color-text-muted); }
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
