<template>
  <div class="co-col">
    <div class="co-col-title">
      <span><FontAwesomeIcon icon="edit" aria-hidden="true" /> {{ isOrder ? '订单信息录入' : '备货信息录入' }}</span>
      <OrderTypeSwitch v-model:form="form" :is-order="isOrder" />
    </div>
    <div class="co-col-scroll">
      <form @submit.prevent="emit('add-staged')">
        <div class="co-form-row">
          <div class="co-form-group">
            <label class="co-label" for="co-date">{{ isOrder ? '订单时间' : '备货时间' }} <span class="co-required" aria-hidden="true">*</span></label>
            <UiDatePicker
              id="co-date"
              :label="isOrder ? '订单时间' : '备货时间'"
              required
              v-model="form.date"
              style="width: 100%"
            />
          </div>
          <div class="co-form-group">
            <label class="co-label" for="co-customer">客户名称 <span class="co-required" aria-hidden="true">*</span></label>
            <UiSelect
              id="co-customer"
              label="客户名称"
              required
              v-model="form.customer"
              placeholder="请选择客户"
              style="width: 100%"
              :options="customerOptions"
            />
          </div>
        </div>

        <div class="co-form-group">
          <label class="co-label" for="co-product">产品名称 <span class="co-required" aria-hidden="true">*</span></label>
          <UiAutocomplete
            id="co-product"
            ref="productRef"
            v-model="form.productSearch"
            required
            :search-fn="searchProducts"
            placeholder="输入产品名称搜索"
            :empty-text="productSearchFailed ? '搜索失败，请重试' : '无匹配结果'"
            @select="selectProduct"
            @update:model-value="form.productId = 0"
          >
            <template #option="{ item }">
              {{ item.name }}
            </template>
          </UiAutocomplete>
        </div>

        <div class="co-form-row">
          <div class="co-form-group">
            <label class="co-label" for="co-quantity">{{ isOrder ? '订单数量' : '备货数量' }} <span class="co-required" aria-hidden="true">*</span></label>
            <input
              id="co-quantity"
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
              aria-required="true"
              :aria-invalid="quantityInvalid ? 'true' : undefined"
              aria-describedby="co-quantity-error"
              @input="quantityTouched = true"
              @blur="quantityTouched = true"
            />
            <p v-if="quantityInvalid" id="co-quantity-error" class="field-error-text" role="alert">
              {{ QUANTITY_RANGE_MESSAGE }}
            </p>
          </div>
          <OrderDeductControl
            v-if="isOrder"
            v-model:form="form"
            :available-stock="availableStock"
            :stock-error="stockError"
            :deduct-info-visible="deductInfoVisible"
            :handle-deduct-preview="handleDeductPreview"
            :open-deduct-edit="openDeductEdit"
          />
        </div>

        <div class="co-form-group">
          <label class="co-label" for="co-note">备注</label>
          <textarea
            id="co-note"
            v-model="form.note"
            rows="2"
            class="co-textarea"
            :placeholder="isOrder ? '例如：加急订单' : '例如：批量备货'"
          />
        </div>

        <OrderExcelImport
          :excel-file="excelFile"
          :importing="importing"
          :is-drag-over="isDragOver"
          :handle-excel-select="handleExcelSelect"
          :on-drop="onDrop"
          :download-template="downloadTemplate"
          :handle-import="handleImport"
          @update:is-drag-over="(v) => emit('update:isDragOver', v)"
        />

        <UiButton variant="primary" style="margin-top: 15px" @click="emit('add-staged')">
          <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />{{ isOrder ? '新增订单' : '新增备货' }}
        </UiButton>
        <!-- 主动说明还缺什么：避免主操作静默不可用 -->
        <p v-if="missingFields.length" class="co-form-hint" aria-live="polite">
          还需填写：{{ missingFields.join('、') }}
        </p>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import OrderTypeSwitch from './OrderTypeSwitch.vue'
import OrderDeductControl from './OrderDeductControl.vue'
import OrderExcelImport from './OrderExcelImport.vue'
import type { FormState, ProductSuggestion } from '../composables/types'
import {
  QUANTITY_MAX,
  QUANTITY_MIN,
  QUANTITY_RANGE_MESSAGE,
  isQuantityOutOfRange,
} from '../composables/quantityRange'

const form = defineModel<FormState>('form', { required: true })

/** 产品输入框引用：提交一条后把焦点交回这里，支持连续录入。
 * UiAutocomplete 是泛型组件，无法用 InstanceType，故按暴露的接口结构声明。 */
const productRef = ref<{ focusInput?: () => void } | null>(null)

/** 供父组件在新增成功后调用 */
function focusProductInput() {
  productRef.value?.focusInput?.()
}

function resetQuantityValidation() {
  quantityTouched.value = false
}

defineExpose({ focusProductInput, resetQuantityValidation })

/**
 * 数量是否已被用户编辑过。
 * 未编辑前不标红：表单初值是 0（"还没填"），那不是"填错了"，
 * 一进页面就把输入框标红属于噪音。用户一旦输入即进入实时校验。
 */
const quantityTouched = ref(false)

/** 数量越界时的字段级错误态；范围与文案统一来自 quantityRange 模块 */
const quantityInvalid = computed(() => quantityTouched.value && isQuantityOutOfRange(form.value.quantity))

defineProps<{
  isOrder: boolean
  customerOptions: { label: string; value: string }[]
  /** 当前还缺的必填项（面向用户的字段名），用于主动提示 */
  missingFields: string[]
  availableStock: number
  deductInfoVisible: boolean
  stockError: string
  excelFile: File | null
  importing: boolean
  isDragOver: boolean
  searchProducts: (q: string) => Promise<ProductSuggestion[]>
  /** 产品搜索是否失败，用于把「搜索失败」与「无匹配结果」区分开 */
  productSearchFailed: boolean
  selectProduct: (item: ProductSuggestion) => void
  handleDeductPreview: () => void
  openDeductEdit: () => void
  handleExcelSelect: (e: Event) => void
  onDrop: (e: DragEvent) => void
  downloadTemplate: () => void
  handleImport: () => void
}>()

const emit = defineEmits<{
  'add-staged': []
  'update:isDragOver': [value: boolean]
}>()
</script>

<style scoped>
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
  outline: none;
  -moz-appearance: textfield;
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

.co-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.co-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.co-col-scroll {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

.co-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.co-form-group {
  margin-bottom: 14px;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.co-required {
  color: var(--color-danger-500);
}
.co-form-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
.co-textarea {
  width: 100%;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
  font-family: inherit;
}
.co-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.co-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.co-textarea::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}
</style>
