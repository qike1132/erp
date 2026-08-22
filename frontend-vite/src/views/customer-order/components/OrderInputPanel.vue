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
            <label class="co-label">订单类型 <span class="co-required">*</span></label>
            <UiSelect
              v-model="form.orderType"
              placeholder="请选择订单类型"
              style="width: 100%"
              :options="orderTypeOptions"
            />
          </div>
          <div v-if="isCustomOrder" class="co-form-group">
            <label class="co-label">国家</label>
            <div style="display: flex; gap: 8px; align-items: center;">
              <UiSelect
                v-model="form.country"
                placeholder="请选择国家"
                style="flex: 1"
                :options="countryOptions"
              />
              <UiButton variant="outline" style="white-space: nowrap; flex-shrink: 0;" @click="openCountryDialog">
                <FontAwesomeIcon icon="plus" aria-hidden="true" />
              </UiButton>
            </div>
          </div>
        </div>
        <div class="co-form-row">
          <div v-if="isOrder" class="co-form-group">
            <label class="co-label">订单时间 <span class="co-required">*</span></label>
            <UiDatePicker v-model="form.date" style="width: 100%" />
          </div>
          <div v-else class="co-form-group">
            <label class="co-label">备货时间 <span class="co-required">*</span></label>
            <UiDatePicker v-model="form.date" style="width: 100%" />
          </div>
          <div class="co-form-group">
            <label class="co-label">客户名称 <span class="co-required">*</span></label>
            <UiSelect
              v-model="form.customer"
              placeholder="请选择客户"
              style="width: 100%"
              :options="customerOptions"
            />
          </div>
        </div>

        <div class="co-form-group">
          <label class="co-label">产品名称 <span class="co-required">*</span></label>
          <UiAutocomplete
            v-model="form.productSearch"
            :search-fn="searchProducts"
            placeholder="输入产品名称搜索"
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
            <label class="co-label">{{ isOrder ? '订单数量' : '备货数量' }} <span class="co-required">*</span></label>
            <input v-model.number="form.quantity" type="number" class="form-number-input" min="1" max="9999999" step="1" style="width: 100%" name="quantity" autocomplete="off" />
          </div>
          <OrderDeductControl
            v-if="isOrder"
            v-model:form="form"
            :available-stock="availableStock"
            :deduct-info-visible="deductInfoVisible"
            :handle-deduct-preview="handleDeductPreview"
            :open-deduct-edit="openDeductEdit"
          />
        </div>

        <div class="co-form-group">
          <label class="co-label">备注</label>
          <textarea
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

        <UiButton variant="primary" :disabled="!canAdd" style="margin-top: 15px" @click="emit('add-staged')">
          <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />{{ isOrder ? '新增订单' : '新增备货' }}
        </UiButton>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import OrderTypeSwitch from './OrderTypeSwitch.vue'
import OrderDeductControl from './OrderDeductControl.vue'
import OrderExcelImport from './OrderExcelImport.vue'
import type { FormState, ProductSuggestion } from '../composables/types'

const form = defineModel<FormState>('form', { required: true })

defineProps<{
  isOrder: boolean
  isCustomOrder: boolean
  orderTypeOptions: { label: string; value: string }[]
  customerOptions: { label: string; value: string }[]
  countryOptions: { label: string; value: string }[]
  canAdd: boolean
  availableStock: number
  deductInfoVisible: boolean
  excelFile: File | null
  importing: boolean
  isDragOver: boolean
  searchProducts: (q: string) => Promise<ProductSuggestion[]>
  selectProduct: (item: ProductSuggestion) => void
  handleDeductPreview: () => void
  openDeductEdit: () => void
  openCountryDialog: () => void
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
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
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
.co-textarea {
  width: 100%;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
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
