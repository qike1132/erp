<template>
  <UiDialog v-model:open="openModel" title="编辑退货">
    <template v-if="form">
      <div class="co-form-group">
        <label class="co-label">客户名称</label>
        <!-- 客户由关联出货明细带出，不可改 -->
        <UiInput :model-value="form.customer" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label">退货时间</label>
        <UiDatePicker v-model="form.date" style="width: 100%" />
      </div>
      <div class="co-form-group">
        <label class="co-label">产品名称</label>
        <UiInput :model-value="form.productName" disabled />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="er-quantity">退货数量</label>
        <input
          id="er-quantity"
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
          aria-label="退货数量"
          :aria-invalid="quantityAriaInvalid(form.quantity)"
          aria-describedby="er-quantity-error"
        />
        <p v-if="quantityInvalid" id="er-quantity-error" class="field-error-text" role="alert">
          {{ QUANTITY_RANGE_MESSAGE }}
        </p>
      </div>
      <div class="co-form-group">
        <label class="co-label" for="er-reason">退货原因</label>
        <UiInput id="er-reason" v-model="form.reason" style="width: 100%" />
      </div>
      <div class="co-form-group">
        <label class="co-label" for="er-note">备注</label>
        <textarea id="er-note" v-model="form.note" rows="2" class="co-textarea" aria-label="备注" />
      </div>
    </template>
    <template #footer>
      <UiButton variant="outline" :disabled="saving" @click="openModel = false"> 取消 </UiButton>
      <UiButton variant="primary" :disabled="saving || quantityInvalid" @click="saveReturnEdit">
        {{ saving ? '保存中…' : '保存' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * EditReturnModal.vue — 退货行编辑弹窗（报表「退货流水」与 /stock-return 退货管理页共用）。
 *
 * 字段与后端 `PUT /stock-returns/{id}` 的 `StockReturnUpdate` 对应：数量 / 退货日期 /
 * 原因 / 备注。客户与产品由关联出货明细带出，不可改。后端实现为单事务内「取消原退货
 * + 按同一出货明细重建」，故保存后新记录带新的 SR 单号（旧记录被删除）。
 *
 * 弹窗只负责呈现与收集，保存流程在 useReportRowActions。
 */
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { ReturnEditForm } from '../composables/useReportRowActions'
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
  saveReturnEdit: () => void
}>()

const form = defineModel<ReturnEditForm | null>('form')

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
