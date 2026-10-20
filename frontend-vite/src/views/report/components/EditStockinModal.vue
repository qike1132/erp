<template>
  <UiDialog v-model:open="openModel" title="编辑备货">
    <template v-if="form">
      <div class="co-form-group">
        <label class="co-label" for="es-stockin-customer">客户名称</label>
        <UiSelect
          id="es-stockin-customer"
          v-model="form.customer"
          style="width: 100%"
          :options="customerOptions"
        />
      </div>
      <div class="co-form-group">
        <label class="co-label">备货时间</label>
        <UiDatePicker v-model="form.date" style="width: 100%" />
      </div>
      <div class="co-form-group">
        <label class="co-label">产品名称</label>
        <!-- 产品不可改：换产品等于换一条备货记录，后端 StockInUpdate 也没有 product_id -->
        <UiInput :model-value="form.productName" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="es-stockin-quantity">备货数量</label>
        <input
          id="es-stockin-quantity"
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
          aria-label="备货数量"
          :aria-invalid="quantityAriaInvalid(form.quantity)"
          aria-describedby="es-stockin-quantity-error"
        />
        <p v-if="quantityInvalid" id="es-stockin-quantity-error" class="field-error-text" role="alert">
          {{ QUANTITY_RANGE_MESSAGE }}
        </p>
      </div>
      <div class="co-form-group">
        <label class="co-label" for="es-stockin-note">备注</label>
        <textarea id="es-stockin-note" v-model="form.note" rows="2" class="co-textarea" aria-label="备注" />
      </div>
    </template>
    <template #footer>
      <UiButton variant="outline" :disabled="saving" @click="openModel = false"> 取消 </UiButton>
      <UiButton variant="primary" :disabled="saving || quantityInvalid" @click="saveStockinEdit">
        {{ saving ? '保存中…' : '保存' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * EditStockinModal.vue — 备货行编辑弹窗（报表页备货流水）
 *
 * 2026-10-06 记录查询 tab 收敛至报表页时自 customer-order/components 迁入。
 * 字段与后端 `PUT /stock/in/edit/{id}` 的 `StockInUpdate` 一一对应：
 * 数量 / 客户 / 备货日期 / 备注。产品刻意不可改 —— 换产品语义上等于换一条备货记录，
 * 后端 schema 也没有 product_id。改数量时后端会按差值同步调整产品当前库存。
 *
 * 弹窗只负责呈现与收集，保存流程（调接口、失效缓存、刷新列表）在 useStockinEdit。
 */
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import type { StockinEditForm } from '../composables/useStockinEdit'
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
  saveStockinEdit: () => void
}>()

const form = defineModel<StockinEditForm | null>('form')

/** 数量越界时的字段级错误态（与主录入、暂存编辑共用同一范围与文案） */
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
