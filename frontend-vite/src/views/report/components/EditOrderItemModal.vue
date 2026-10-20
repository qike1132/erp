<template>
  <UiDialog v-model:open="openModel" title="编辑订单明细">
    <template v-if="form">
      <div class="co-form-group">
        <label class="co-label">产品名称</label>
        <!-- 产品不可改：换产品等于换一条明细，后端 OrderItemUpdate 也没有 product_id -->
        <UiInput :model-value="form.productName" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="eoi-quantity">数量</label>
        <input
          id="eoi-quantity"
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
          aria-label="数量"
          :aria-invalid="quantityAriaInvalid(form.quantity)"
          aria-describedby="eoi-quantity-error"
        />
        <p v-if="quantityInvalid" id="eoi-quantity-error" class="field-error-text" role="alert">
          {{ QUANTITY_RANGE_MESSAGE }}
        </p>
      </div>
      <div class="co-form-group">
        <label class="co-label" for="eoi-note">备注</label>
        <textarea id="eoi-note" v-model="form.note" rows="2" class="co-textarea" aria-label="备注" />
      </div>
    </template>
    <template #footer>
      <UiButton variant="outline" :disabled="saving" @click="openModel = false"> 取消 </UiButton>
      <UiButton variant="primary" :disabled="saving || quantityInvalid" @click="saveOrderItemEdit">
        {{ saving ? '保存中…' : '保存' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * EditOrderItemModal.vue — 订单流水行内编辑单个 SKU 的弹窗。
 *
 * 字段与后端 `PUT /orders/items/{id}` 的 `OrderItemUpdate` 一一对应：数量 / 备注。
 * 客户是订单级字段，不在此改。改数量后后端重算订单兼容数量与状态。
 * 弹窗只负责呈现与收集，保存流程（调接口、失效缓存、刷新列表）在 useReportRowActions。
 */
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { OrderItemEditForm } from '../composables/useReportRowActions'
import {
  QUANTITY_MAX,
  QUANTITY_MIN,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
  quantityAriaInvalid,
} from '@/utils/quantity'

const props = defineProps<{
  open: boolean
  saving: boolean
  saveOrderItemEdit: () => void
}>()

const form = defineModel<OrderItemEditForm | null>('form')
const quantityInvalid = computed(() => isQuantityOutOfRange(form.value?.quantity))

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})
</script>

<style scoped lang="scss">
@use './edit-modals.scss' as *;
</style>
